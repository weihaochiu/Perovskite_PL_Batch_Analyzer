from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
from matplotlib.figure import Figure

from pl_core import build_fit_curve_data


REPLICATE_SUFFIX = re.compile(r"[-_]\d+$")


@dataclass(frozen=True)
class ConditionGroup:
    """Finite replicate values collected at one categorical X position."""

    name: str
    values: tuple[float, ...]
    labels: tuple[str, ...]


def normalize_condition(condition="", sample_id="", output_code="", filename=""):
    """Return a display condition after removing only a terminal replicate number."""
    candidates = (condition, sample_id, output_code, Path(str(filename)).stem if filename else "")
    for candidate in candidates:
        value = "" if candidate is None else str(candidate).strip()
        if not value:
            continue
        normalized = REPLICATE_SUFFIX.sub("", value).strip()
        return normalized or value
    return "Unknown"


def natural_sort_key(value):
    """Case-insensitive key that compares digit runs numerically."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(value))
        if part
    )


def select_dominant_peak(result):
    """Select the sole peak, or largest area when all areas are valid, else height."""
    peaks = list(getattr(result, "peaks", ()) or ())
    if not peaks:
        return None
    if len(peaks) == 1:
        return peaks[0]
    def has_finite_metric(peak, name):
        try:
            return bool(np.isfinite(float(getattr(peak, name))))
        except (AttributeError, TypeError, ValueError):
            return False

    if all(has_finite_metric(peak, "area") for peak in peaks):
        return max(peaks, key=lambda peak: float(peak.area))
    finite_height_peaks = [peak for peak in peaks if has_finite_metric(peak, "height")]
    if finite_height_peaks:
        return max(finite_height_peaks, key=lambda peak: float(peak.height))
    return peaks[0]


def group_condition_values(records, value_selector, value_name="value"):
    """Group finite dominant-peak values without changing the source records."""
    grouped = {}
    warnings = []
    for label, spectrum, result in records:
        peak = select_dominant_peak(result)
        if peak is None:
            warnings.append(f"{label}: no fitted peak; skipped in {value_name} by condition.")
            continue
        try:
            value = float(value_selector(peak))
        except (AttributeError, TypeError, ValueError) as exc:
            warnings.append(f"{label}: invalid {value_name} ({exc}); skipped in condition plot.")
            continue
        if not np.isfinite(value):
            warnings.append(f"{label}: non-finite {value_name}; skipped in condition plot.")
            continue
        name = normalize_condition(
            getattr(spectrum, "condition", ""),
            getattr(spectrum, "sample_id", ""),
            label,
            getattr(spectrum, "source_name", ""),
        )
        key = name.casefold()
        if key not in grouped:
            grouped[key] = {"name": name, "values": [], "labels": []}
        grouped[key]["values"].append(value)
        grouped[key]["labels"].append(str(label))
    groups = [
        ConditionGroup(item["name"], tuple(item["values"]), tuple(item["labels"]))
        for item in grouped.values()
    ]
    groups.sort(key=lambda group: natural_sort_key(group.name))
    return groups, warnings


def categorical_parameter_figure(records, value_selector, ylabel, title):
    """Plot replicate points and per-condition mean/sample-SD summaries."""
    groups, warnings = group_condition_values(records, value_selector, ylabel)
    if not groups:
        warnings.append(f"No finite data available for {title}.")
        return None, warnings

    fig = Figure(figsize=(8, 5), constrained_layout=True)
    ax = fig.subplots()
    individual_x = []
    individual_y = []
    means = []
    error_values = []
    error_x = []
    bounds = []
    for x_position, group in enumerate(groups):
        values = np.asarray(group.values, dtype=float)
        mean = float(np.mean(values))
        individual_x.extend([x_position] * len(values))
        individual_y.extend(values)
        means.append(mean)
        bounds.extend(values)
        if len(values) >= 2:
            sample_sd = float(np.std(values, ddof=1))
            error_x.append(x_position)
            error_values.append(sample_sd)
            bounds.extend((mean - sample_sd, mean + sample_sd))

    ax.scatter(
        individual_x,
        individual_y,
        s=38,
        alpha=0.45,
        color="tab:blue",
        edgecolors="none",
        label="Individual replicate",
        zorder=3,
    )
    positions = np.arange(len(groups))
    ax.scatter(
        positions,
        means,
        s=92,
        color="white",
        edgecolors="black",
        linewidths=1.4,
        label="Mean",
        zorder=5,
    )
    if error_x:
        error_means = [means[position] for position in error_x]
        ax.errorbar(
            error_x,
            error_means,
            yerr=error_values,
            fmt="none",
            ecolor="black",
            elinewidth=1.2,
            capsize=4,
            label="Mean ± SD",
            zorder=4,
        )

    finite_bounds = np.asarray(bounds, dtype=float)
    low = float(np.min(finite_bounds))
    high = float(np.max(finite_bounds))
    span = high - low
    padding = span * 0.08 if span > 0 else max(abs(low) * 0.05, 1e-9)
    ax.set_ylim(low - padding, high + padding)
    ax.set_xticks(positions, [group.name for group in groups])
    if max(map(len, (group.name for group in groups))) > 12 or sum(len(group.name) for group in groups) > 50:
        ax.tick_params(axis="x", labelrotation=35)
        for tick in ax.get_xticklabels():
            tick.set_horizontalalignment("right")
    ax.set(xlabel="Condition", ylabel=ylabel, title=title)
    ax.grid(axis="y", color="0.85", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend()
    return fig, warnings

def selected_fit_figure(result):
    curves=build_fit_curve_data(result)
    fig=Figure(figsize=(10,7),constrained_layout=True); axs=fig.subplots(2,2)
    ax=axs[0,0]; ax.plot(curves.photon_energy_ev,curves.raw_intensity,label="Raw"); ax.plot(curves.photon_energy_ev,curves.total_fit,label="Total fit")
    if curves.baseline is not None:ax.plot(curves.photon_energy_ev,curves.baseline,label="Baseline",linestyle=":")
    for i,c in enumerate(curves.components,1): ax.plot(curves.photon_energy_ev,c,label=f"Peak {i}",linestyle="--")
    ax.set(xlabel="Photon energy (eV)",ylabel="PL intensity",title=f"{result.temperature_k:g} K: {result.model}, {result.n_peaks} peak(s)"); ax.legend()
    axs[0,1].plot(curves.photon_energy_ev,curves.residual); axs[0,1].axhline(0,linewidth=.8); axs[0,1].set(xlabel="Photon energy (eV)",ylabel="Residual",title="Residual")
    axs[1,0].plot(curves.photon_energy_ev,curves.raw_intensity,label="Raw"); axs[1,0].plot(curves.photon_energy_ev,curves.total_fit,label="Fit"); axs[1,0].set_yscale("log"); axs[1,0].set(xlabel="Photon energy (eV)",ylabel="PL intensity (log)",title="Log view")
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
