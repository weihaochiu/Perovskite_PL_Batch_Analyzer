import numpy as np, pandas as pd
from pl_core import prepare_spectrum,fit_spectrum,fit_temperature

def test_peak_fit():
    wl=np.linspace(700,850,700); ev=1239.841984/wl; y=1000*np.exp(-4*np.log(2)*((ev-1.55)/0.055)**2)+10
    s=prepare_spectrum(pd.DataFrame({'wl':wl,'pl':y}),'wl','pl',temperature_k=300)
    r=fit_spectrum(s,model='Gaussian',n_peaks=1,baseline_mode='Constant',use_jacobian=False)
    assert abs(r.peaks[0].center_ev-1.55)<0.002
    assert abs(r.peaks[0].fwhm_ev-0.055)<0.003

def test_temperature_linear():
    T=np.array([100,150,200,250,300.]); y=1.6+2e-4*T
    r=fit_temperature(T,y,'Peak energy','Linear')
    assert abs(r.parameters['slope_eV_per_K']-2e-4)<1e-8
