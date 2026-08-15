from __future__ import annotations
import json,re,sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
import numpy as np
from PySide6.QtCore import Qt,QSettings,QStandardPaths,QThread,Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import *
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas,NavigationToolbar2QT

from batch_worker import BatchFitWorker,append_jsonl
from pl_core import read_table,numeric_columns
from plotting import selected_fit_figure,overlay_figure,parameter_figure,contour_figure
from export_manager import export_all

APP_VERSION="0.4.0"
HEADERS=["Use","Export","Condition","Sample ID","Temperature (K)","Direction","Output code","File","X column","PL column","Status"]
SUPPORTED_SPECTRUM_EXTENSIONS={".asc",".csv",".dat",".tsv",".txt",".xls",".xlsx"}
SPECTRUM_FILE_FILTER="Spectra (*.csv *.txt *.dat *.tsv *.xls *.xlsx *.asc);;ASC files (*.asc)"

class DropTable(QTableWidget):
    def __init__(self,parent): super().__init__(parent); self.setAcceptDrops(True)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self,e):
        paths=[u.toLocalFile() for u in e.mimeData().urls()]; self.parent().add_paths(paths); e.acceptProposedAction()

class MainWindow(QMainWindow):
    batch_completed = Signal(object)
    batch_progressed = Signal(object)

    def __init__(self):
        super().__init__(); self.setWindowTitle(f"Perovskite Steady-State PL Batch Analyzer v{APP_VERSION}"); self.resize(1500,900)
        self.settings=QSettings("WeiHaoChiu","PerovskiteSSPLAnalyzer"); self.records=[]; self.results=[]; self.tempfits={}; self.figures={}
        self._batch_thread=None; self._batch_worker=None; self._batch_errors=[]; self._last_batch_summary=None; self._close_pending=False
        self.checkpoint_path=None; self.timing_log_path=None; self.batch_log_directory=None; self._build()
    def _build(self):
        tb=QToolBar(); self.addToolBar(tb)
        self.toolbar_actions={}
        for text,slot in [("Add spectra",self.add_files),("Open project",self.open_project),("Save project",self.save_project),("Batch fit",self.analyze),("Export",self.export)]:
            a=QAction(text,self); a.triggered.connect(slot); tb.addAction(a); self.toolbar_actions[text]=a
        self.batch_action=self.toolbar_actions["Batch fit"]; self.export_action=self.toolbar_actions["Export"]
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
        buttons=QHBoxLayout(); self.file_buttons=[]
        for t,s in [("Add files",self.add_files),("Remove",self.remove_selected),("Move up",lambda:self.move(-1)),("Move down",lambda:self.move(1))]: b=QPushButton(t); b.clicked.connect(s); buttons.addWidget(b); self.file_buttons.append(b)
        rv.addLayout(buttons)
        self.table=DropTable(self); self.table.setColumnCount(len(HEADERS)); self.table.setHorizontalHeaderLabels(HEADERS); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); self.table.itemSelectionChanged.connect(self.show_selected); rv.addWidget(self.table,2)
        progress_box=QGroupBox("Batch fit progress"); progress_layout=QGridLayout(progress_box)
        self.progress_file=QLabel("Idle"); self.progress_counts=QLabel("0 / 0 (0.0%)"); self.progress_timing=QLabel("Single: --   ETA: --")
        self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,1000); self.progress_bar.setValue(0)
        self.cancel_batch_button=QPushButton("Cancel Batch Fit"); self.cancel_batch_button.setEnabled(False); self.cancel_batch_button.clicked.connect(self.cancel_batch)
        progress_layout.addWidget(QLabel("Current file"),0,0); progress_layout.addWidget(self.progress_file,0,1,1,2)
        progress_layout.addWidget(self.progress_counts,1,0); progress_layout.addWidget(self.progress_bar,1,1); progress_layout.addWidget(self.cancel_batch_button,1,2)
        progress_layout.addWidget(self.progress_timing,2,0,1,3); rv.addWidget(progress_box)
        self.tabs=QTabWidget(); rv.addWidget(self.tabs,3); splitter.addWidget(right); splitter.setSizes([330,1150])
        self.status=QStatusBar(); self.setStatusBar(self.status)
        self.fit_controls=[self.x_type,self.model,self.npeaks,self.baseline,self.jacobian,self.fit_lo,self.fit_hi,self.inst,self.energy_model,self.fwhm_model,self.int_model]
    def add_files(self):
        p,_=QFileDialog.getOpenFileNames(self,"Add spectra","",SPECTRUM_FILE_FILTER); self.add_paths(p)
    def add_paths(self,paths):
        for path in paths:
            if Path(path).suffix.lower() not in SUPPORTED_SPECTRUM_EXTENSIONS: continue
            try:
                df=read_table(path); cols=numeric_columns(df)
                if len(cols)<2: raise ValueError("No two numeric columns found")
                stem=Path(path).stem; tm=re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[Kk](?!\w)",stem); T=float(tm.group(1)) if tm else 300.0
                condition=re.sub(r"[_-]?\d+(?:\.\d+)?\s*[Kk].*","",stem).strip("_- ") or stem
                rec={"use":True,"export":True,"condition":condition,"sample_id":condition,"temperature":T,"direction":"Isothermal","code":stem,"path":str(path),"x":cols[0],"y":cols[1],"status":"Ready"}; self.records.append(rec); self._add_row(rec)
            except Exception as exc: QMessageBox.warning(self,"匯入失敗",f"檔案：{Path(path).name}\n原因：{exc}")
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

    @staticmethod
    def _duration(seconds):
        if seconds is None:return "--"
        seconds=max(0,int(round(seconds))); minutes,seconds=divmod(seconds,60); hours,minutes=divmod(minutes,60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def _set_batch_running(self,running):
        self.batch_action.setEnabled(not running); self.export_action.setEnabled(not running); self.table.setEnabled(not running)
        for button in self.file_buttons:button.setEnabled(not running)
        for widget in self.fit_controls:widget.setEnabled(not running)
        for name in ("Add spectra","Open project","Save project"):self.toolbar_actions[name].setEnabled(not running)
        self.cancel_batch_button.setEnabled(running)

    def _batch_settings(self):
        fitrange=(self.fit_lo.value(),self.fit_hi.value()) if self.fit_hi.value()>self.fit_lo.value()>0 else None
        return {"x_type":self.x_type.currentText(),"model":self.model.currentText(),"npeaks":self.npeaks.currentText(),"baseline":self.baseline.currentText(),"jacobian":self.jacobian.isChecked(),"fit_range":fitrange,"instrument_fwhm_mev":self.inst.value(),"energy_model":self.energy_model.currentText(),"fwhm_model":self.fwhm_model.currentText(),"intensity_model":self.int_model.currentText()}

    def analyze(self):
        if self._batch_thread is not None:return
        self._sync(); tasks=[(index,record) for index,record in enumerate(self.records) if record["use"]]
        if not tasks:
            QMessageBox.information(self,"Batch fit","沒有勾選要分析的檔案。"); return
        self._clear_tabs(); self.results=[]; self.tempfits={}; self._batch_errors=[]; self._last_batch_summary=None
        for index,_ in tasks:self.records[index]["status"]="Queued"; self.table.item(index,10).setText("Queued")
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_root=Path(self.batch_log_directory) if self.batch_log_directory else Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))/"batch_runs"
        self.checkpoint_path=str(log_root/f"batch_checkpoint_{stamp}.jsonl"); self.timing_log_path=str(log_root/f"batch_timing_{stamp}.jsonl")
        self.progress_file.setText("Starting..."); self.progress_counts.setText(f"0 / {len(tasks)} (0.0%)"); self.progress_bar.setValue(0); self.progress_timing.setText("Single: --   ETA: --")
        self._set_batch_running(True); self.status.showMessage("Batch fit running in background...")
        thread=QThread(self); worker=BatchFitWorker(tasks,self._batch_settings(),self.checkpoint_path,self.timing_log_path); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.item_started.connect(self._on_item_started); worker.item_completed.connect(self._on_item_completed); worker.item_failed.connect(self._on_item_failed); worker.progress.connect(self._on_batch_progress); worker.warning.connect(self._on_batch_warning); worker.finished.connect(self._on_batch_finished); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(self._on_batch_thread_finished); thread.finished.connect(thread.deleteLater)
        self._batch_thread=thread; self._batch_worker=worker; thread.start()

    def cancel_batch(self):
        if self._batch_worker is None:return
        self._batch_worker.request_cancel(); self.cancel_batch_button.setEnabled(False); self.progress_file.setText("Cancelling after current file..."); self.status.showMessage("Cancellation requested; completed results will be kept.")

    def _on_item_started(self,payload):
        index=payload["row_index"]; self.records[index]["status"]="Fitting"; self.table.item(index,10).setText("Fitting"); self.progress_file.setText(payload["source"])

    def _on_item_completed(self,payload):
        index=payload["row_index"]; self.results.append((payload["label"],payload["spectrum"],payload["result"])); self.records[index]["status"]="OK"; self.table.item(index,10).setText("OK")

    def _on_item_failed(self,payload):
        index=payload["row_index"]; self.records[index]["status"]="Failed"; self.table.item(index,10).setText("Failed"); self._batch_errors.append(f"檔案 {payload['source']}：{payload['error']}")

    def _on_batch_progress(self,payload):
        self.progress_file.setText(payload["source"]); self.progress_counts.setText(f"{payload['completed']} / {payload['total']} ({payload['percent']:.1f}%)"); self.progress_bar.setValue(round(payload["percent"]*10)); self.progress_timing.setText(f"Single: {payload['file_elapsed']:.2f} s   ETA: {self._duration(payload['eta'])}"); self.batch_progressed.emit(payload)

    def _on_batch_warning(self,message):
        self._batch_errors.append(message); self.status.showMessage(message,10000)

    def _on_batch_finished(self,summary):
        self.tempfits=summary["tempfits"]; self._batch_errors.extend(error for error in summary["errors"] if error not in self._batch_errors)
        plot_started=perf_counter(); self.refresh_tabs(); plot_elapsed=perf_counter()-plot_started
        try:append_jsonl(self.timing_log_path,{"type":"batch_stage","stage":"plot","seconds":plot_elapsed})
        except Exception as exc:self._batch_errors.append(f"plot timing log 寫入失敗：{exc}")
        summary=dict(summary); summary["plot_elapsed"]=plot_elapsed; summary["errors"]=list(self._batch_errors); self._last_batch_summary=summary
        if summary["cancelled"]:
            message=f"Cancelled: kept {len(self.results)} completed result(s)"
        else:message=f"Completed: {len(self.results)} / {summary['total']} spectra"
        self.status.showMessage(f"{message} | Checkpoint: {summary['checkpoint_path']}"); self.progress_file.setText("Cancelled" if summary["cancelled"] else "Completed"); self._set_batch_running(False); self.batch_completed.emit(summary)
        if self._batch_errors and not self._close_pending:QMessageBox.warning(self,"完成，但有警告","下列檔案或分析未完成：\n"+"\n".join(self._batch_errors[:20]))

    def _on_batch_thread_finished(self):
        self._batch_worker=None; self._batch_thread=None
        if self._close_pending:self.close()
    def refresh_tabs(self):
        self._clear_tabs()
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

    def _dispose_tab(self,index):
        widget=self.tabs.widget(index)
        if widget is None:return
        self.tabs.removeTab(index)
        for canvas in widget.findChildren(FigureCanvas):
            canvas.figure.clear(); canvas.close(); canvas.deleteLater()
        widget.deleteLater()

    def _clear_tabs(self):
        while self.tabs.count():self._dispose_tab(0)
        for figure in self.figures.values():figure.clear()
        self.figures={}

    def show_selected(self):
        rows=self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or not self.results:return
        idx=rows[0].row(); code=self.records[idx]["code"]
        for l,s,r in self.results:
            if l==code:
                old=self.figures.pop("selected_fit",None)
                if self.tabs.count():self._dispose_tab(0)
                if old is not None:old.clear()
                fig=selected_fit_figure(r); w=QWidget(); v=QVBoxLayout(w); c=FigureCanvas(fig); v.addWidget(NavigationToolbar2QT(c,w)); v.addWidget(c); self.tabs.insertTab(0,w,"Selected fit"); self.tabs.setCurrentIndex(0); self.figures["selected_fit"]=fig; break
    def export(self):
        if self._batch_thread is not None:return
        if not self.results:
            self.analyze(); return
        d=QFileDialog.getExistingDirectory(self,"Export folder");
        if not d:return
        started=perf_counter()
        try:
            export_all(d,[r for r in self.results if next((x["export"] for x in self.records if x["code"]==r[0]),True)],self.tempfits,self.figures)
        finally:
            elapsed=perf_counter()-started
            if self.timing_log_path:
                try:append_jsonl(self.timing_log_path,{"type":"batch_stage","stage":"export","seconds":elapsed,"output":d})
                except Exception as exc:self.status.showMessage(f"export timing log 寫入失敗：{exc}",10000)
        QMessageBox.information(self,"Export complete",d)
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

    def closeEvent(self,event):
        if self._batch_thread is not None:
            self._close_pending=True; self.cancel_batch(); event.ignore(); return
        self._clear_tabs(); event.accept()

def main():
    app=QApplication(sys.argv); app.setStyle("Fusion"); w=MainWindow(); w.show(); sys.exit(app.exec())
if __name__=="__main__": main()
