from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd
from pl_core import result_to_dict

def export_all(outdir, rows, tempfits, figures):
    out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
    peak_rows=[]; curve_sheets={}; residual_sheets={}
    for label,spec,res in rows:
        for p in res.peaks:
            peak_rows.append({"Label":label,"Condition":spec.condition,"Sample ID":spec.sample_id,"Temperature_K":spec.temperature_k,"Model":res.model,"N peaks":res.n_peaks,"Peak":p.peak_index,"Center_eV":p.center_ev,"Center_nm":p.center_nm,"FWHM_meV":p.fwhm_mev,"Height":p.height,"Area":p.area,"Area_fraction":p.area_fraction,"R2":res.r_squared,"Adjusted_R2":res.adjusted_r_squared,"RMSE":res.rmse,"AICc":res.aicc,"BIC":res.bic,"Warnings":"; ".join(res.warnings)})
        key=(label[:22]+f"_{spec.temperature_k:g}K")[:31]
        d={"Energy_eV":res.x_ev,"Raw":res.y_raw,"Total_fit":res.y_fit,"Baseline":res.baseline}
        for i,c in enumerate(res.components,1): d[f"Peak_{i}"]=c
        curve_sheets[key]=pd.DataFrame(d); residual_sheets[key]=pd.DataFrame({"Energy_eV":res.x_ev,"Residual":res.residual})
    temp_rows=[]
    for label,group in tempfits.items():
        for kind,r in group.items():
            for name,val in r.parameters.items():
                lo,hi=r.ci95[name]; temp_rows.append({"Label":label,"Analysis":kind,"Model":r.model,"Parameter":name,"Value":val,"SE":r.errors[name],"CI95_low":lo,"CI95_high":hi,"R2":r.r_squared,"Adjusted_R2":r.adjusted_r_squared,"RMSE":r.rmse,"AICc":r.aicc,"BIC":r.bic,"Warnings":"; ".join(r.warnings)})
    with pd.ExcelWriter(out/"PL_batch_results.xlsx",engine="openpyxl") as w:
        pd.DataFrame(peak_rows).to_excel(w,"Peak_Results",index=False)
        pd.DataFrame(temp_rows).to_excel(w,"Temperature_Fits",index=False)
        for k,v in curve_sheets.items(): v.to_excel(w,("Fit_"+k)[:31],index=False)
        for k,v in residual_sheets.items(): v.to_excel(w,("Res_"+k)[:31],index=False)
    pd.DataFrame(peak_rows).to_csv(out/"peak_results.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(temp_rows).to_csv(out/"temperature_fit_results.csv",index=False,encoding="utf-8-sig")
    payload={"spectra":[{"label":l,"spectrum":{"condition":s.condition,"sample_id":s.sample_id,"temperature_k":s.temperature_k,"source_name":s.source_name},"fit":result_to_dict(r)} for l,s,r in rows],"temperature_fits":{l:{k:result_to_dict(v) for k,v in g.items()} for l,g in tempfits.items()}}
    (out/"analysis_results.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    for name,fig in figures.items():
        fig.savefig(out/f"{name}.png",dpi=300); fig.savefig(out/f"{name}.pdf")
