# models.py
# Data classes for GeoLog AI
# SampleEntry — holds all data for one spoon sample
# BoreholeLog — holds borehole header info + list of SampleEntry objects
# Scope: Soil only. Rock core to be added later.

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SampleEntry:
    # ── Sample identification ──
    depth_ft: float
    depth_m: float
    sample_type: str          # "SS" for split spoon, "RC" for rock core
    sample_no: int

    # ── SPT data ──
    blow_counts: list
    pen_depths: list
    n_value: int
    n_value_log: str
    refusal: bool
    recovery_inches: Optional[float] = None
    recovery_mm: Optional[int] = None
    cone_blow_ft: Optional[str] = None

    # ── Field screening ──
    cgd_ppm: Optional[float] = None
    pid_ppm: Optional[float] = None

    # ── Description ──
    raw_transcript: str = ""
    description: str = ""
    flags: list = field(default_factory=list)

    # ── Comments ──
    comments: Optional[str] = None

    # ── Metadata ──
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))



@dataclass
class BoreholeLog:
    """
    Holds borehole header information and a growing list of SampleEntry objects.
    Created at the start of a logging session.
    Samples are added one at a time as they are logged in the field.
    """

    # ── Required header fields ──
    borehole_no: str            # e.g. "BH25-1"
    tech: str                   # field technician name
    drilling_method: str        # e.g. "Hollow Stem Auger"
    od_augers: str              # auger diameter e.g. "203mm"
    date_started: str           # date drilling started
    driller: str                # drilling company
    sheet_no: int = 1
    total_sheets: int = 1
    # ── Optional header fields ──                  
    weather: Optional[str] = None                
    drilling_rig: str = ""
    hammer_weight: Optional[str] = None   # lbs
    hammer_drop: Optional[str] = None     # inches
    water_level_depth: Optional[float] = None   # m
    cave_in: Optional[float] = None             # m
    
    # ── Sample entries — grows as logging progresses ──
    samples: list = field(default_factory=list)

    def add_sample(self, sample: SampleEntry):
        self.samples.append(sample)
        

    def total_samples(self) -> int:
        return len(self.samples)

    def get_sample(self, sample_no: int) -> Optional[SampleEntry]:
        # YOUR CODE HERE — return the sample with the matching sample_no
        for sample in self.samples:
            if sample.sample_no == sample_no:
                return sample
        return None
class Project:
     # ── Required header fields ──
    project_no: str                 # project reference number e.g. "25-1021"
    client: str                 # client name
    project_name: str                # project name
    location: str               # site location      

    boreholes: list = field(default_factory=list)  

    def add_borehole(self,borehole:BoreholeLog):
        self.boreholes.append(borehole)

    def total_boreholes(self):
        return len(self.boreholes)
    
    def get_borehole(self,borehole_no):
        for borehole in self.boreholes:
            if borehole.borehole_no != borehole_no:
                return None
            else:
                return borehole