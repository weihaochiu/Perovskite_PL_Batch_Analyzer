from __future__ import annotations
import json,re,sys,traceback,zipfile
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt,QSettings
from PySide6.QtGui import QAction,QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import *
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas,NavigationToolbar2QT

from pl_core import read_table,numeric_columns,prepare_spectrum,fit_spectrum,fit_best_model,fit_temperature
from plotting import selected_fit_figure,overlay_figure,parameter_figure,contour_figure
from export_manager import export_all

APP_VERSION="0.4.0"
HEADERS=["Use","Export","Condition","Sample ID","Temperature (K)","Direction","Output code","File","X column","PL column","Status"]

class DropTable(QTableWidget):
    def __init__(self,parent): super().__init__(parent); self.setAcceptDrops(True)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self,e):
        paths=[u.toLocalFile() for u in e.mimeData().urls()]; self.parent().add_paths(paths); e.acceptProposedAction()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(f"Perovskite Steady-State PL Batch Analyzer v{APP_VERSION}"); self.resize(1500,900)
        self.settings=QSettings("WeiHaoChiu","PerovskiteSSPLAnalyzer"); self.records=[]; self.results=[]; self.tempfits={}; self.figures={}; self._build()
    def _build(self):
        tb=QToolBar(); self.addToolBar(tb)
        for text,slot in [("Add spectra",self.add_files),("Open project",self.open_project),("Save project",self.save_project),("Batch fit",self.analyze),("Export",self.export)]:
            a=QAction(text,self); a.triggered.connect(slot); tb.addAction(a)
        splitter=QSplitter(); self.setCentralWidget(splitter)
        controls=QWidget(); form=QVBoxLayout(controls)
        g=QGroupBox("Shared fitting settings"); gf=QFormLayout(g)
        self.x_type=QComboBox(); self.x_type.addItems(["Wavelength (nm)","Photon energy (eV)"]); gf.addRow("X type",self.x_type)
        self.model=QComboBox(); self.model.addItems(["Automatic","Gaussian","Lorentzian","Pseudo-Voigt","Voigt"]); gf.addRow("Peak model",self.model)
        self.npeaks=QComboBox(); self.npeaks.addItems(["Auto (1–2)","1","2","3"]); gf.addRow("Peak count",self.npeaks)
        self.baseline=QComboBox(); self.baseline.addItems(["Constant","Linear","None"]); gf.addRow("Baseline",self.baseline)
        self.jacobian=QCheckBox("Jacobian-corrected energy spectrum"); self.jacobian.setChecked(True); gf.addRow(self.jacobian)
        self.fit_lo=QDoubleSpinBox(); self.fit_lo.setRange(0,10); self.fit_lo.setDecimals(4); self.fit_lo.setValue(0)
        self.fit_hi=QDoubleSpinBox(); self.fit_hi.setRange(0,10); self.fit_hi.setDecimals(4); self.fit_hi.setValue(0)
        row=QWidget(); h=QHBoxLayout(row); h.setContentsMargins(0,0,0,0); h.addWidget(self.fit_lo); h.addWidget(QLabel("to")); h.addWidget(self.fit_hi); gf.addRow("Fit range eV (0=auto)",row)
        self.inst=QDoubleSpinBox(); self.inst.setRange(0,1000); self.inst.setSuffix(" meV"); gf.addRow("Instrument FWHM",self.inst)
        form.addWidget(g)
        tg=QGroupBox("Temperature fitting models"); tf=QFormLayout(tg)
        self.energy_model=QComboBox(); self.energy_model.addItems(["Linear","Varshni","Bose-Einstein"]); tf.addRow("Peak energy",self.energy_model)
        self.fwhm_model=QComboBox(); self.fwhm_model.addItems(["Linear","LO phonon","Full phonon"]); tf.addRow("FWHM",self.fwhm_model)
        self.int_model=QComboBox(); self.int_model.addItems(["One-channel Arrhenius","Two-channel Arrhenius"]); tf.addRow("Integrated intensity",self.int_model)
        form.addWidget(tg); form.addStretch(); splitter.addWidget(controls)
        right=QWidget(); rv=QVBoxLayout(right)
        buttons=QHBoxLayout()
        for t,s in [("Add files",self.add_files),("Remove",self.remove_selected),("Move up",lambda:self.move(-1)),("Move down",lambda:self.move(1))]: b=QPushButton(t); b.clicked.connect(s); buttons.addWidget(b)
        rv.addLayout(buttons)
        self.table=DropTable(self); self.table.setColumnCount(len(HEADERS)); self.table.setHorizontalHeaderLabels(HEADERS); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); self.table.itemSelectionChanged.connect(self.show_selected); rv.addWidget(self.table,2)
        self.tabs=QTabWidget(); rv.addWidget(self.tabs,3); splitter.addWidget(right); splitter.setSizes([330,1150])
        self.status=QStatusBar(); self.setStatusBar(self.status)
    def add_files(self):
        p,_=QFileDialog.getOpenFileNames(self,"Add spectra","","Spectra (*.csv *.txt *.dat *.tsv *.xls *.xlsx)"); self.add_paths(p)
    def add_paths(self,paths):
        for path in paths:
            if not Path(path).suffix.lower() in {".csv",".txt",".dat",".tsv",".xls",".xlsx"}: continue
            try:
                df=read_table(path); cols=numeric_columns(df)
                if len(cols)<2: raise ValueError("No two numeric columns found")
                stem=Path(path).stem; tm=re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[Kk](?!\w)",stem); T=float(tm.group(1)) if tm else 300.0
                condition=re.sub(r"[_-]?\d+(?:\.\d+)?\s*[Kk].*","",stem).strip("_- ") or stem
                rec={"use":True,"export":True,"condition":condition,"sample_id":condition,"temperature":T,"direction":"Isothermal","code":stem,"path":str(path),"x":cols[0],"y":cols[1],"status":"Ready"}; self.records.append(rec); self._add_row(rec)
            except Exception as exc: QMessageBox.warning(self,"Import failed",f"{path}\n{exc}")
    def _add_row(self,r):
        row=self.table.rowCount(); self.table.insertRow(row)
        for c,key in enumerate(["use","export"]):
            it=QTableWidgetItem(); it.setFlags(it.flags()|Qt.ItemIsUserCheckable); it.setCheckState(Qt.Checked if r[key] else Qt.Unchecked); self.table.setItem(row,c,it)
        vals=[r["condition"],r["sample_id"],str(r["temperature"]),r["direction"],r["code"],Path(r["path"]).name,r["x"],r["y"],r["status"]]
        for j,v in enumerate(vals,2): self.table.setItem(row,j,QTableWidgetItem(v))
    def _sync(self):
        for i,r in enumerate(self.records):
            r.update(use=self.table.item(i,0).checkState()==Qt.Checked,export=self.table.item(i,1).checkState()==Qt.Checked,condition=self.table.item(i,2).text(),sample_id=self.table.item(i,3).text(),temperature=float(self.table.item(i,4).text()),direction=self.table.item(i,5).text(),code=self.table.item(i,6).text(),x=self.table.item(i,8).text(),y=self.table.item(i,9).text())
    def remove_selected(self):
        rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()},reverse=True)
        for i in rows: self.table.removeRow(i); self.records.pop(i)
    def move(self,d):
        self._sync(); rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()});
        if not rows:return
        if d<0 and rows[0]==0:return
        if d>0 and rows[-1]==len(self.records)-1:return
        indices=rows if d<0 else list(reversed(rows))
        for i in indices: self.records[i],self.records[i+d]=self.records[i+d],self.records[i]
        self.table.setRowCount(0)
        for r in self.records:self._add_row(r)
        for i in [r+d for r in rows]:self.table.selectRow(i)
    def analyze(self):
        self._sync(); self.results=[]; self.tempfits={}; self.status.showMessage("Analyzing...")
        fitrange=(self.fit_lo.value(),self.fit_hi.value()) if self.fit_hi.value()>self.fit_lo.value()>0 else None
        errors=[]
        for i,r in enumerate(self.records):
            if not r["use"]:continue
            try:
                df=read_table(r["path"]); spec=prepare_spectrum(df,r["x"],r["y"],x_type=self.x_type.currentText(),temperature_k=r["temperature"],condition=r["condition"],sample_id=r["sample_id"],source_name=Path(r["path"]).name)
                if self.model.currentText()=="Automatic" or self.npeaks.currentText().startswith("Auto"):
                    models=("Gaussian","Pseudo-Voigt","Voigt") if self.model.currentText()=="Automatic" else (self.model.currentText(),)
                    maxp=2 if self.npeaks.currentText().startswith("Auto") else int(self.npeaks.currentText()); res,_=fit_best_model(spec,models=models,max_peaks=maxp,baseline_mode=self.baseline.currentText(),fit_range_ev=fitrange,use_jacobian=self.jacobian.isChecked())
                else: res=fit_spectrum(spec,model=self.model.currentText(),n_peaks=int(self.npeaks.currentText()),baseline_mode=self.baseline.currentText(),fit_range_ev=fitrange,use_jacobian=self.jacobian.isChecked(),instrument_fwhm_mev=self.inst.value())
                self.results.append((r["code"],spec,res)); r["status"]="OK"; self.table.item(i,10).setText("OK")
            except Exception as exc: r["status"]="Failed"; self.table.item(i,10).setText("Failed"); errors.append(f"{r['code']}: {exc}")
        groups={}
        for label,spec,res in self.results: groups.setdefault(spec.condition,[]).append((label,spec,res))
        for cond,items in groups.items():
            if len({s.temperature_k for _,s,_ in items})<3:continue
            items=sorted(items,key=lambda z:z[1].temperature_k); T=np.array([s.temperature_k for _,s,_ in items]); e=np.array([r.peaks[0].center_ev for _,s,r in items]); fw=np.array([r.peaks[0].fwhm_mev for _,s,r in items]); area=np.array([sum(p.area for p in r.peaks) for _,s,r in items]); self.tempfits[cond]={}
            for kind,vals,model in [("Peak energy",e,self.energy_model.currentText()),("FWHM",fw,self.fwhm_model.currentText()),("Integrated intensity",area,self.int_model.currentText())]:
                try:self.tempfits[cond][kind]=fit_temperature(T,vals,kind,model)
                except Exception as exc:errors.append(f"{cond} {kind}: {exc}")
        self.refresh_tabs(); self.status.showMessage(f"Completed: {len(self.results)} spectra")
        if errors: QMessageBox.warning(self,"Completed with warnings","\n".join(errors[:20]))
    def refresh_tabs(self):
        self.tabs.clear(); self.figures={}
        if not self.results:return
        self._add_fig("Selected fit",selected_fit_figure(self.results[0][2]),"selected_fit")
        self._add_fig("Raw overlay",overlay_figure(self.results,False),"raw_overlay"); self._add_fig("Normalized overlay",overlay_figure(self.results,True),"normalized_overlay")
        groups={}
        for l,s,r in self.results:groups.setdefault(s.condition,[]).append((l,s,r))
        for cond,items in groups.items():
            if len(items)>=3:
                self._add_fig(f"Contour: {cond}",contour_figure(items,f"{cond}: temperature-dependent PL"),f"contour_{cond}")
        for kind,ylabel,title in [("Peak energy","Peak energy (eV)","Peak energy vs temperature"),("FWHM","FWHM (meV)","FWHM vs temperature"),("Integrated intensity","Normalized integrated PL intensity","Integrated PL intensity vs temperature")]:
            series=[]; fits={}
            for cond,items in groups.items():
                items=sorted(items,key=lambda z:z[1].temperature_k); T=np.array([s.temperature_k for _,s,_ in items]);
                if kind=="Peak energy":y=np.array([r.peaks[0].center_ev for _,s,r in items])
                elif kind=="FWHM":y=np.array([r.peaks[0].fwhm_mev for _,s,r in items])
                else:y=np.array([sum(p.area for p in r.peaks) for _,s,r in items]); y=y/y.max()
                series.append((cond,T,y));
                if cond in self.tempfits and kind in self.tempfits[cond]:fits[cond]=self.tempfits[cond][kind]
            self._add_fig(kind,parameter_figure(series,ylabel,title,fits),kind.lower().replace(" ","_"))
    def _add_fig(self,title,fig,key):
        w=QWidget(); v=QVBoxLayout(w); c=FigureCanvas(fig); v.addWidget(NavigationToolbar2QT(c,w)); v.addWidget(c); self.tabs.addTab(w,title); self.figures[key]=fig
    def show_selected(self):
        rows=self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or not self.results:return
        idx=rows[0].row(); code=self.records[idx]["code"]
        for l,s,r in self.results:
            if l==code:
                self.tabs.removeTab(0); fig=selected_fit_figure(r); w=QWidget(); v=QVBoxLayout(w); c=FigureCanvas(fig); v.addWidget(NavigationToolbar2QT(c,w)); v.addWidget(c); self.tabs.insertTab(0,w,"Selected fit"); self.tabs.setCurrentIndex(0); self.figures["selected_fit"]=fig; break
    def export(self):
        if not self.results:self.analyze()
        if not self.results:return
        d=QFileDialog.getExistingDirectory(self,"Export folder");
        if not d:return
        export_all(d,[r for r in self.results if next((x["export"] for x in self.records if x["code"]==r[0]),True)],self.tempfits,self.figures); QMessageBox.information(self,"Export complete",d)
    def save_project(self):
        self._sync(); p,_=QFileDialog.getSaveFileName(self,"Save project","project.plproj","PL project (*.plproj)");
        if not p:return
        tmp=Path(p); payload={"version":APP_VERSION,"records":self.records,"settings":{"x_type":self.x_type.currentText(),"model":self.model.currentText(),"npeaks":self.npeaks.currentText(),"baseline":self.baseline.currentText(),"jacobian":self.jacobian.isChecked(),"energy_model":self.energy_model.currentText(),"fwhm_model":self.fwhm_model.currentText(),"int_model":self.int_model.currentText()}}
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    def open_project(self):
        p,_=QFileDialog.getOpenFileName(self,"Open project","","PL project (*.plproj)");
        if not p:return
        data=json.loads(Path(p).read_text(encoding="utf-8")); self.records=data["records"]; self.table.setRowCount(0)
        for r in self.records:self._add_row(r)
        s=data.get("settings",{});
        for widget,key in [(self.x_type,"x_type"),(self.model,"model"),(self.npeaks,"npeaks"),(self.baseline,"baseline"),(self.energy_model,"energy_model"),(self.fwhm_model,"fwhm_model"),(self.int_model,"int_model")]:
            if key in s:widget.setCurrentText(s[key])
        self.jacobian.setChecked(s.get("jacobian",True))

def main():
    app=QApplication(sys.argv); app.setStyle("Fusion"); w=MainWindow(); w.show(); sys.exit(app.exec())
if __name__=="__main__": main()
