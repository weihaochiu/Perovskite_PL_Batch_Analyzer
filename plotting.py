from __future__ import annotations
import numpy as np
from matplotlib.figure import Figure

def selected_fit_figure(result):
    fig=Figure(figsize=(10,7),constrained_layout=True); axs=fig.subplots(2,2)
    ax=axs[0,0]; ax.plot(result.x_ev,result.y_raw,label="Raw"); ax.plot(result.x_ev,result.y_fit,label="Total fit")
    for i,c in enumerate(result.components,1): ax.plot(result.x_ev,c+result.baseline,label=f"Peak {i}",linestyle="--")
    ax.set(xlabel="Photon energy (eV)",ylabel="PL intensity",title=f"{result.temperature_k:g} K: {result.model}, {result.n_peaks} peak(s)"); ax.legend()
    axs[0,1].plot(result.x_ev,result.residual); axs[0,1].axhline(0,linewidth=.8); axs[0,1].set(xlabel="Photon energy (eV)",ylabel="Residual",title="Residual")
    axs[1,0].plot(result.x_ev,result.y_raw,label="Raw"); axs[1,0].plot(result.x_ev,result.y_fit,label="Fit"); axs[1,0].set_yscale("log"); axs[1,0].set(xlabel="Photon energy (eV)",ylabel="PL intensity (log)",title="Log view")
    text=[f"R² = {result.r_squared:.6f}",f"Adj. R² = {result.adjusted_r_squared:.6f}",f"RMSE = {result.rmse:.4g}",f"AICc = {result.aicc:.2f}",f"BIC = {result.bic:.2f}"]
    for p in result.peaks: text += [f"Peak {p.peak_index}: {p.center_ev:.5f} eV / {p.center_nm:.2f} nm",f"FWHM: {p.fwhm_mev:.2f} meV; Area: {p.area:.4g}"]
    axs[1,1].axis("off"); axs[1,1].text(0,.98,"\n".join(text),va="top",family="monospace")
    return fig

def overlay_figure(records,normalized=False):
    fig=Figure(figsize=(8,5),constrained_layout=True); ax=fig.subplots()
    for label,spec,res in records:
        y=spec.intensity_energy.copy(); y=y/y.max() if normalized and y.max()!=0 else y
        ax.plot(spec.photon_energy_ev,y,label=label)
    ax.set(xlabel="Photon energy (eV)",ylabel="Normalized PL intensity" if normalized else "PL intensity",title="PL spectra overlay"); ax.legend()
    return fig

def parameter_figure(series, ylabel, title, fit_results=None):
    fig=Figure(figsize=(8,5),constrained_layout=True); ax=fig.subplots()
    for label,T,y in series:
        ax.plot(T,y,marker="o",label=label)
        if fit_results and label in fit_results:
            r=fit_results[label]; ax.plot(r.temperature_k,r.fitted,linestyle="--")
    ax.set(xlabel="Temperature (K)",ylabel=ylabel,title=title); ax.legend(); return fig

def contour_figure(records,title):
    fig=Figure(figsize=(8,5),constrained_layout=True); ax=fig.subplots()
    records=sorted(records,key=lambda z:z[1].temperature_k); grid=np.linspace(max(min(s.photon_energy_ev) for _,s,_ in records),min(max(s.photon_energy_ev) for _,s,_ in records),500)
    T=[]; Z=[]
    for _,s,_ in records:
        T.append(s.temperature_k); z=np.interp(grid,s.photon_energy_ev,s.intensity_energy); Z.append(z/max(z.max(),1e-30))
    im=ax.pcolormesh(grid,np.asarray(T),np.asarray(Z),shading="auto"); fig.colorbar(im,ax=ax,label="Normalized PL intensity"); ax.set(xlabel="Photon energy (eV)",ylabel="Temperature (K)",title=title); return fig
