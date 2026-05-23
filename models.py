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
    layers: Optional[list] = None

    # ── Structured soil fields (Chunk 1) ──
    # Persisted to dedicated Supabase columns so the NL query layer can filter
    # on color, moisture, plasticity, etc. without parsing the description prose.
    soil_name: Optional[str] = None              # primary soil name (e.g. "sand", "silty clay")
    particle_size_range: Optional[str] = None    # fine / medium / coarse / fine to medium / etc.
    color: Optional[str] = None
    moisture: Optional[str] = None
    plasticity: Optional[str] = None
    gradation: Optional[str] = None
    consistency: Optional[str] = None            # cohesive — derived from N
    density: Optional[str] = None                # granular — derived from N
    uscs_symbol: Optional[str] = None
    fill: Optional[bool] = None
    inclusions: Optional[list] = None
    components: Optional[list] = None
    descriptor_fields: Optional[dict] = None     # ASTM D2488 catch-all (JSONB)
    depth_start_ft: Optional[float] = None
    depth_end_ft: Optional[float] = None

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

    # ── Location + datum (Chunk 2) ──
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ground_elevation_ft: Optional[float] = None
    datum: Optional[str] = None                       # NAD83, NAVD88, etc.
    depth_reference_datum: Optional[str] = None       # ground surface / casing top / benchmark

    # ── Termination + groundwater (Chunk 2) ──
    total_depth_ft: Optional[float] = None
    termination_reason: Optional[str] = None          # refusal / planned_depth / obstruction / other
    groundwater: Optional[dict] = None                # {encountered_ft, stabilized_ft, date_measured, dry}

    # ── Drilling equipment (Chunk 2) ──
    hammer_type: Optional[str] = None                 # automatic / safety / donut
    hammer_efficiency: Optional[float] = None         # ratio, used for N60 correction
    sampler_id: Optional[str] = None
    borehole_diameter_in: Optional[float] = None

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

@dataclass
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
            if borehole.borehole_no == borehole_no:
                return borehole
        
        return None