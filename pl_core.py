from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
import json, math
from time import perf_counter

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.special import wofz
from scipy.signal import find_peaks, savgol_filter

HC_EV_NM = 1239.841984
KB_EV_K = 8.617333262145e-5

@dataclass
class PLSpectrum:
    wavelength_nm: np.ndarray
    photon_energy_ev: np.ndarray
    intensity_wavelength: np.ndarray
    intensity_energy: np.ndarray
    temperature_k: float
    condition: str
    sample_id: str
    source_name: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass
class PeakResult:
    peak_index: int
    center_ev: float
    center_nm: float
    fwhm_ev: float
    fwhm_mev: float
    height: float
    area: float
    area_fraction: float
    parameters: dict
    errors: dict

@dataclass
class SpectrumFitResult:
    temperature_k: float
    model: str
    n_peaks: int
    peaks: list[PeakResult]
    x_ev: np.ndarray
    y_raw: np.ndarray
    y_fit: np.ndarray
    components: list[np.ndarray]
    baseline: np.ndarray
    residual: np.ndarray
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    reduced_chi2: float
    aic: float
    aicc: float
    bic: float
    warnings: list[str]

@dataclass
class TemperatureFitResult:
    analysis_type: str
    model: str
    parameters: dict
    errors: dict
    ci95: dict
    temperature_k: np.ndarray
    observed: np.ndarray
    fitted: np.ndarray
    residual: np.ndarray
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    aic: float
    aicc: float
    bic: float
    warnings: list[str]


def read_asc(path: str | Path) -> pd.DataFrame:
    """Read the leading two-column spectrum block from an ASCII ASC file."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"無法讀取 ASC 檔案：{exc}") from exc

    wavelength = []
    intensity = []
    metadata: dict[str, str] = {}
    data_started = False
    data_finished = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if data_started:
                data_finished = True
            continue

        parts = stripped.split()
        numeric_pair = False
        if not data_finished and len(parts) == 2:
            try:
                x_value, y_value = (float(value) for value in parts)
                numeric_pair = math.isfinite(x_value) and math.isfinite(y_value)
            except ValueError:
                numeric_pair = False

        if numeric_pair:
            data_started = True
            wavelength.append(x_value)
            intensity.append(y_value)
            continue

        data_finished = True
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key, value = key.strip(), value.strip()
            if key:
                metadata[key] = value

    if not wavelength:
        raise ValueError("找不到位於檔案開頭、由兩個有限數值組成的光譜資料列。")
    if len(wavelength) != len(intensity):
        raise ValueError("波長與 PL 強度欄位的資料長度不一致。")
    if len(wavelength) < 12:
        raise ValueError(f"有效光譜點不足：找到 {len(wavelength)} 點，至少需要 12 點。")

    df = pd.DataFrame(
        {
            "Wavelength_nm": np.asarray(wavelength, dtype=float),
            "PL_Intensity": np.asarray(intensity, dtype=float),
        }
    )
    df.attrs["metadata"] = metadata
    df.attrs["source_format"] = "ASC"
    return df


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".asc":
        return read_asc(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        last = None
        for opts in ({"sep": None, "engine": "python"}, {"sep": r"[\t,; ]+", "engine": "python"}):
            try:
                df = pd.read_csv(path, **opts)
                if df.shape[1] >= 2:
                    break
            except Exception as exc:
                last = exc
        else:
            raise ValueError(f"Unable to parse file: {last}")
    if df.shape[1] < 2:
        raise ValueError("At least two columns are required.")
    return df


def numeric_columns(df: pd.DataFrame) -> list[str]:
    out=[]
    for c in df.columns:
        s=pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= max(5, int(len(df)*0.25)):
            out.append(str(c))
    return out


def prepare_spectrum(df: pd.DataFrame, x_column: str, y_column: str, *, x_type: str="Wavelength (nm)", temperature_k: float=300.0, condition: str="Sample", sample_id: str="Sample-1", source_name: str="") -> PLSpectrum:
    x=pd.to_numeric(df[x_column], errors="coerce").to_numpy(float)
    y=pd.to_numeric(df[y_column], errors="coerce").to_numpy(float)
    m=np.isfinite(x)&np.isfinite(y)&(x>0)
    x,y=x[m],y[m]
    if len(x)<12: raise ValueError("At least 12 valid data points are required.")
    if x_type.startswith("Wavelength"):
        wl=x; ev=HC_EV_NM/wl
    else:
        ev=x; wl=HC_EV_NM/ev
    order=np.argsort(ev)
    ev,wl,y=ev[order],wl[order],y[order]
    compact=pd.DataFrame({"ev":ev,"wl":wl,"y":y}).groupby("ev",as_index=False).mean(numeric_only=True)
    ev=compact.ev.to_numpy(); wl=compact.wl.to_numpy(); y=compact.y.to_numpy()
    # spectral density transformation |d lambda / dE| = hc / E^2
    y_ev=y*HC_EV_NM/np.square(ev)
    metadata=dict(df.attrs.get("metadata", {}))
    return PLSpectrum(wl,ev,y,y_ev,float(temperature_k),condition,sample_id,source_name,metadata)


def gaussian(x, center, fwhm, height):
    return height*np.exp(-4*np.log(2)*((x-center)/fwhm)**2)

def lorentzian(x, center, fwhm, height):
    return height/(1+4*((x-center)/fwhm)**2)

def pseudo_voigt(x, center, fwhm, height, eta):
    return eta*lorentzian(x,center,fwhm,height)+(1-eta)*gaussian(x,center,fwhm,height)

def voigt_profile(x, center, fwhm_g, fwhm_l, height):
    sigma=max(fwhm_g,1e-12)/(2*np.sqrt(2*np.log(2)))
    gamma=max(fwhm_l,1e-12)/2
    z=((x-center)+1j*gamma)/(sigma*np.sqrt(2))
    v=np.real(wofz(z))/(sigma*np.sqrt(2*np.pi))
    vmax=np.max(v)
    return height*v/vmax if vmax>0 else np.zeros_like(x)

def _voigt_fwhm(fg,fl):
    return 0.5346*fl+np.sqrt(0.2166*fl*fl+fg*fg)

def _component(model,x,p):
    if model=="Gaussian": return gaussian(x,*p)
    if model=="Lorentzian": return lorentzian(x,*p)
    if model=="Pseudo-Voigt": return pseudo_voigt(x,*p)
    if model=="Voigt": return voigt_profile(x,*p)
    raise ValueError(model)

def _npp(model): return {"Gaussian":3,"Lorentzian":3,"Pseudo-Voigt":4,"Voigt":4}[model]

def _baseline(x, pars, mode):
    if mode=="None": return np.zeros_like(x)
    if mode=="Constant": return np.full_like(x,pars[0])
    if mode=="Linear": return pars[0]+pars[1]*(x-np.mean(x))
    raise ValueError(mode)

def _baseline_count(mode): return {"None":0,"Constant":1,"Linear":2}[mode]

def _model_func(model,n_peaks,baseline_mode):
    n=_npp(model)
    def f(x,*params):
        y=np.zeros_like(x,float)
        for i in range(n_peaks): y += _component(model,x,params[i*n:(i+1)*n])
        return y+_baseline(x,params[n*n_peaks:],baseline_mode)
    return f

def _initial_peaks(x,y,n_peaks,model):
    ys=savgol_filter(y, min(len(y)//2*2-1, 21), 3) if len(y)>=9 else y
    distance=max(2,len(y)//(n_peaks+2))
    inds,_=find_peaks(ys,prominence=max(np.ptp(ys)*0.015,1e-12),distance=distance)
    inds=sorted(inds,key=lambda i:ys[i],reverse=True)[:n_peaks]
    if len(inds)<n_peaks:
        candidates=np.linspace(int(len(x)*0.25),int(len(x)*0.75),n_peaks,dtype=int)
        inds=(inds+list(candidates))[:n_peaks]
    inds=sorted(inds,key=lambda i:x[i])
    span=max(np.ptp(x),1e-3)
    p=[]
    for i in inds:
        c=float(x[i]); h=float(max(y[i]-np.percentile(y,5),np.ptp(y)*0.1,1e-9)); fw=span/(5*n_peaks)
        if model in {"Gaussian","Lorentzian"}: p += [c,fw,h]
        elif model=="Pseudo-Voigt": p += [c,fw,h,0.5]
        else: p += [c,fw*0.7,fw*0.3,h]
    return p

def _add_timing(timings: dict[str, float] | None, stage: str, started: float) -> None:
    if timings is not None:
        timings[stage] = timings.get(stage, 0.0) + perf_counter() - started


def fit_spectrum(spec: PLSpectrum, *, model: str="Pseudo-Voigt", n_peaks: int=1, baseline_mode: str="Constant", fit_range_ev: tuple[float,float]|None=None, use_jacobian: bool=True, initial: list[float]|None=None, instrument_fwhm_mev: float=0.0, timings: dict[str,float]|None=None) -> SpectrumFitResult:
    x=spec.photon_energy_ev.copy(); y=(spec.intensity_energy if use_jacobian else spec.intensity_wavelength).copy()
    if fit_range_ev:
        lo,hi=sorted(fit_range_ev); m=(x>=lo)&(x<=hi); x,y=x[m],y[m]
    if len(x)<max(15,5*n_peaks): raise ValueError("Too few points in fitting range.")
    y=np.asarray(y,float)
    n=_npp(model); nb=_baseline_count(baseline_mode)
    started=perf_counter()
    try:
        p0=list(initial) if initial else _initial_peaks(x,y,n_peaks,model)
    finally:
        _add_timing(timings,"initial_guess",started)
    base0=float(np.percentile(y,3))
    if baseline_mode=="Constant": p0 += [base0]
    elif baseline_mode=="Linear": p0 += [base0,0.0]
    xmin,xmax=float(x.min()),float(x.max()); span=xmax-xmin; ymax=max(float(np.max(y)),1e-9)
    lower=[]; upper=[]
    for _ in range(n_peaks):
        if model in {"Gaussian","Lorentzian"}:
            lower += [xmin,span/1000,0]; upper += [xmax,span,ymax*20]
        elif model=="Pseudo-Voigt":
            lower += [xmin,span/1000,0,0]; upper += [xmax,span,ymax*20,1]
        else:
            lower += [xmin,span/1000,span/1000,0]; upper += [xmax,span,span,ymax*20]
    if baseline_mode=="Constant": lower += [-ymax*5]; upper += [ymax*5]
    elif baseline_mode=="Linear": lower += [-ymax*5,-ymax*50/span]; upper += [ymax*5,ymax*50/span]
    func=_model_func(model,n_peaks,baseline_mode)
    started=perf_counter()
    try:
        popt,pcov=curve_fit(func,x,y,p0=p0,bounds=(lower,upper),maxfev=100000)
    finally:
        _add_timing(timings,"optimization",started)
    perr=np.sqrt(np.maximum(np.diag(pcov),0))
    yfit=func(x,*popt); resid=y-yfit
    ssr=float(np.sum(resid**2)); sst=float(np.sum((y-y.mean())**2)); r2=1-ssr/sst if sst>0 else 0
    k=len(popt); N=len(y); adj=1-(1-r2)*(N-1)/(N-k-1) if N>k+1 else float("nan")
    rmse=float(np.sqrt(ssr/N)); red=float(ssr/max(N-k,1)); eps=np.finfo(float).tiny
    aic=float(N*np.log(max(ssr/N,eps))+2*k); aicc=float(aic+2*k*(k+1)/(N-k-1)) if N>k+1 else float("inf"); bic=float(N*np.log(max(ssr/N,eps))+k*np.log(N))
    comps=[]; peaks=[]; areas=[]
    for i in range(n_peaks):
        pp=popt[i*n:(i+1)*n]; ee=perr[i*n:(i+1)*n]; comp=_component(model,x,pp); comps.append(comp); area=float(np.trapezoid(comp,x)); areas.append(area)
    total=max(sum(areas),np.finfo(float).tiny)
    warnings=[]
    for i in range(n_peaks):
        pp=popt[i*n:(i+1)*n]; ee=perr[i*n:(i+1)*n]
        if model in {"Gaussian","Lorentzian"}: center,fw,height=pp; names=["center_ev","fwhm_ev","height"]
        elif model=="Pseudo-Voigt": center,fw,height,eta=pp; names=["center_ev","fwhm_ev","height","eta"]
        else: center,fg,fl,height=pp; fw=_voigt_fwhm(fg,fl); names=["center_ev","fwhm_g_ev","fwhm_l_ev","height"]
        corrected=math.sqrt(max(fw*fw-(instrument_fwhm_mev/1000)**2,0)) if instrument_fwhm_mev>0 else fw
        if corrected<=0: warnings.append(f"Peak {i+1}: linewidth is at/below instrument resolution.")
        pars={name:float(v) for name,v in zip(names,pp)}; errs={name:float(v) for name,v in zip(names,ee)}
        peaks.append(PeakResult(i+1,float(center),float(HC_EV_NM/center),float(corrected),float(corrected*1000),float(height),areas[i],float(areas[i]/total),pars,errs))
    order=np.argsort([p.center_ev for p in peaks]); peaks=[peaks[i] for i in order]; comps=[comps[i] for i in order]
    if any(p.area_fraction<0.01 for p in peaks): warnings.append("One or more components contribute <1% of total fitted area.")
    baseline=_baseline(x,popt[n*n_peaks:],baseline_mode)
    return SpectrumFitResult(spec.temperature_k,model,n_peaks,peaks,x,y,yfit,comps,baseline,resid,float(r2),float(adj),rmse,red,aic,aicc,bic,warnings)


def fit_best_model(spec: PLSpectrum, *, models=("Gaussian","Pseudo-Voigt","Voigt"), max_peaks=2, baseline_mode="Constant", fit_range_ev=None, use_jacobian=True, timings: dict[str,float]|None=None):
    results=[]
    for model in models:
        for n in range(1,max_peaks+1):
            try: results.append(fit_spectrum(spec,model=model,n_peaks=n,baseline_mode=baseline_mode,fit_range_ev=fit_range_ev,use_jacobian=use_jacobian,timings=timings))
            except Exception: pass
    if not results: raise RuntimeError("All fitting models failed.")
    results.sort(key=lambda r:r.bic)
    best=results[0]
    # prefer simpler result unless BIC improves materially
    for r in results:
        if r.n_peaks<best.n_peaks and r.bic-best.bic<6: best=r
    return best,results


def _stats(y,yfit,k):
    y=np.asarray(y); yfit=np.asarray(yfit); resid=y-yfit; N=len(y); ssr=float(np.sum(resid**2)); sst=float(np.sum((y-y.mean())**2)); r2=1-ssr/sst if sst>0 else 0
    adj=1-(1-r2)*(N-1)/(N-k-1) if N>k+1 else float("nan"); rmse=float(np.sqrt(ssr/N)); eps=np.finfo(float).tiny
    aic=float(N*np.log(max(ssr/N,eps))+2*k); aicc=float(aic+2*k*(k+1)/(N-k-1)) if N>k+1 else float("inf"); bic=float(N*np.log(max(ssr/N,eps))+k*np.log(N))
    return resid,r2,adj,rmse,aic,aicc,bic

def fit_temperature(T,y,analysis_type: Literal["Peak energy","FWHM","Integrated intensity"],model: str):
    T=np.asarray(T,float); y=np.asarray(y,float); m=np.isfinite(T)&np.isfinite(y); T,y=T[m],y[m]; o=np.argsort(T); T,y=T[o],y[o]
    if len(T)<3: raise ValueError("At least 3 temperature points are required.")
    warnings=[]
    if analysis_type=="Peak energy":
        if model=="Linear":
            f=lambda t,e0,m:e0+m*t; p0=[y[0],(y[-1]-y[0])/max(T[-1]-T[0],1)]; bounds=([-np.inf,-np.inf],[np.inf,np.inf]); names=["E0_eV","slope_eV_per_K"]
        elif model=="Varshni":
            f=lambda t,e0,alpha,beta:e0-alpha*t*t/(t+beta); p0=[max(y),5e-4,200]; bounds=([0,-0.02,1],[5,0.02,5000]); names=["E0_eV","alpha_eV_per_K","beta_K"]
        elif model=="Bose-Einstein":
            f=lambda t,e0,c,eph:e0-c*(1/np.tanh(eph/(2*KB_EV_K*t))-1); p0=[y[0],0.02,0.015]; bounds=([0,-2,1e-4],[5,2,0.2]); names=["E0_eV","coupling_eV","phonon_energy_eV"]
        else: raise ValueError(model)
    elif analysis_type=="FWHM":
        if model=="Linear":
            f=lambda t,g0,gac:g0+gac*t; p0=[max(y.min(),1),0.03]; bounds=([0,-10],[1000,10]); names=["Gamma0_meV","gamma_ac_meV_per_K"]
        elif model=="LO phonon":
            f=lambda t,g0,glo,elo:g0+glo/(np.exp(elo/(KB_EV_K*1000*t))-1); p0=[max(y.min(),1),50,15]; bounds=([0,0,0.1],[1000,5000,200]); names=["Gamma0_meV","Gamma_LO_meV","E_LO_meV"]
        elif model=="Full phonon":
            f=lambda t,g0,gac,glo,elo:g0+gac*t+glo/(np.exp(elo/(KB_EV_K*1000*t))-1); p0=[max(y.min(),1),0.02,50,15]; bounds=([0,-10,0,0.1],[1000,10,5000,200]); names=["Gamma0_meV","gamma_ac_meV_per_K","Gamma_LO_meV","E_LO_meV"]
            if len(T)<8: warnings.append("Full phonon model is weakly constrained with fewer than 8 temperatures.")
            if np.ptp(T)<150: warnings.append("Temperature span <150 K; LO phonon parameters may be unreliable.")
        else: raise ValueError(model)
    else:
        yn=y/y.max()
        if model=="One-channel Arrhenius":
            f=lambda t,i0,a,ea:i0/(1+a*np.exp(-ea/(KB_EV_K*1000*t))); p0=[1,10,30]; bounds=([0,0,0.01],[10,1e8,1000]); names=["I0","A","Ea_meV"]
        elif model=="Two-channel Arrhenius":
            f=lambda t,i0,a1,e1,a2,e2:i0/(1+a1*np.exp(-e1/(KB_EV_K*1000*t))+a2*np.exp(-e2/(KB_EV_K*1000*t))); p0=[1,5,15,20,60]; bounds=([0,0,0.01,0,0.01],[10,1e8,1000,1e8,1000]); names=["I0","A1","Ea1_meV","A2","Ea2_meV"]
            if len(T)<8: warnings.append("Two-channel Arrhenius model is weakly constrained with fewer than 8 temperatures.")
        else: raise ValueError(model)
        y=yn
    popt,pcov=curve_fit(f,T,y,p0=p0,bounds=bounds,maxfev=200000)
    perr=np.sqrt(np.maximum(np.diag(pcov),0)); yfit=f(T,*popt); resid,r2,adj,rmse,aic,aicc,bic=_stats(y,yfit,len(popt))
    pars={n:float(v) for n,v in zip(names,popt)}; errs={n:float(v) for n,v in zip(names,perr)}; ci={n:(float(v-1.96*e),float(v+1.96*e)) for n,v,e in zip(names,popt,perr)}
    if np.any(~np.isfinite(perr)) or any(e>abs(v)*2+1e-12 for v,e in zip(popt,perr)): warnings.append("One or more parameters are weakly constrained.")
    if analysis_type=="Integrated intensity": warnings.append("Activation energy is reported as PL-quenching activation energy, not automatically as trap depth or exciton binding energy.")
    return TemperatureFitResult(analysis_type,model,pars,errs,ci,T,y,yfit,resid,float(r2),float(adj),rmse,aic,aicc,bic,warnings)


def result_to_dict(obj):
    def conv(v):
        if isinstance(v,np.ndarray): return v.tolist()
        if hasattr(v,"__dataclass_fields__"): return {k:conv(val) for k,val in asdict(v).items()}
        if isinstance(v,dict): return {k:conv(val) for k,val in v.items()}
        if isinstance(v,list): return [conv(i) for i in v]
        return v
    return conv(obj)
