"""Physical constants and scoring parameters, each with its source.

SOURCES
  [T]    Magic tech file for sky130A, open_pdks sky130/magic/sky130.tech
         (github.com/RTimothyEdwards/open_pdks, commit 61a056e, 2026-05-25),
         extract style ngspice, sky130A (#else !RERAM) branch.
         Units per the file: aF/um^2 (area), aF/um (perimeter/sidewall),
         milliohm/sq (sheet), milliohm per cut (contacts).
  [MAG]  Magic source extract/ExtCouple.c extSideCommon():
         C_sidewall = coef * L_parallel / (s + offset)   (aF, um)
  [LEF]  SkyWater tech LEF sky130_fd_sc_hd.tlef (google/skywater-pdk-libs-
         sky130_fd_sc_hd, tech/), DCCURRENTDENSITY AVERAGE at Tj = 90 C.
         Not the design-rule manual; the official SkyWater docs carry no EM
         table (periphery rule x.4 is "NC").
  [RCX]  skywater-pdk.readthedocs.io rules/rcx (docs/rules/rcx/*.tsv):
         inter-layer parallel/fringe caps agree with [T] to rounding.
  [ASSUME] Explicit prototype assumption; not from a PDK document.
"""

# --- capacitance, [T] lines 5628-5914 ---------------------------------------
# area cap to substrate (aF/um^2), perimeter (fringe) cap to substrate (aF/um)
AREA_CAP = {"li1": 36.99, "met1": 25.78, "met2": 17.5, "met3": 12.37, "met4": 8.42, "met5": 6.32}
PERIM_CAP = {"li1": 40.70, "met1": 40.57, "met2": 37.76, "met3": 40.99, "met4": 36.68, "met5": 38.85}
# sidewall coupling coefficient (aF) and offset (um): C = coef*L/(s+offset)  [T]+[MAG]
SIDEWALL = {"li1": (25.5, 0.14), "met1": (44.0, 0.25), "met2": (50.0, 0.30),
            "met3": (74.0, 0.40), "met4": (94.0, 0.57), "met5": (155.0, 0.50)}
SIDEHALO_UM = 8.0  # [T] L5248 'sidehalo 8': Magic ignores coupling beyond 8 um
# overlap cap between layers (aF/um^2), key = (upper, lower)  [T] / [RCX]
OVERLAP_CAP = {("met1", "li1"): 114.20, ("met2", "met1"): 133.86, ("met3", "met2"): 86.19,
               ("met4", "met3"): 84.03, ("met5", "met4"): 68.33,
               ("met3", "met1"): 34.54, ("met4", "met2"): 20.33, ("met5", "met3"): 19.63}
# fringe from the upper layer's edge down onto the lower layer (aF/um) [T]
FRINGE_DOWN = {("met1", "li1"): 59.50, ("met2", "met1"): 67.05, ("met3", "met2"): 69.85,
               ("met4", "met3"): 70.52, ("met5", "met4"): 82.82}

# device capacitances for the victim's own total capacitance  [ASSUME]
COX_F_PER_UM2 = 8.3e-15   # eps_ox/tox with tox ~ 4.15 nm (1.8 V SKY130 BSIM4 toxe order) [ASSUME]
CJ_F_PER_UM2 = 1.0e-15    # S/D junction area cap, order of magnitude for SKY130 n+/p+ [ASSUME]
CMIM_F_PER_UM2 = 2.0e-15  # MIM cap density ~2 fF/um^2 (sky130 cap_mim_m3 nominal order) [ASSUME]

# minimum width / spacing per layer (um), SkyWater tech LEF [LEF] (li1 0.17/0.17)
MIN_WIDTH = {"li1": 0.17, "met1": 0.14, "met2": 0.14, "met3": 0.30, "met4": 0.30, "met5": 1.60}
MIN_SPACE = {"li1": 0.17, "met1": 0.14, "met2": 0.14, "met3": 0.30, "met4": 0.30, "met5": 1.60}

# --- resistance, [T] L5400-5432 (converted to ohm) -----------------------------
SHEET_RES = {"li1": 12.8, "met1": 0.125, "met2": 0.125, "met3": 0.047, "met4": 0.047, "met5": 0.029}
VIA_RES = {"mcon": 9.3, "via": 4.5, "via2": 3.41, "via3": 3.41, "via4": 0.38}
# NOTE: the official RCX table lists MCON 152 ohm / LICON 15 ohm, which conflicts
# with [T] (mcon 9.3 ohm, licon-poly 152 ohm).  [T] is used; treat mcon R as unconfirmed.

# --- electromigration, [LEF] DC average at Tj = 90 C ---------------------------
EM_MA_PER_UM = {"met1": 2.8, "met2": 2.8, "met3": 6.8, "met4": 6.8, "met5": 10.17}
# li1 has no public EM number.  [ASSUME] 0.1x met1 (li1 is ~0.1 um thick vs 0.36 um
# met1 and ~100x more resistive); flagged as an assumption in every report.
EM_MA_PER_UM["li1"] = 0.28
EM_VIA_MA = {"mcon": 0.36, "via": 0.29, "via2": 0.48, "via3": 0.48, "via4": 2.49}

# Fixed engineering measurement calibration. Parameters exposed by the final
# scorer (weights, saturation, raw-area/aspect limits) are stored elsewhere.
P = {'cc_full': 0.1,
 'cc_zero': 0.5,
 'sym_full': 0.05,
 'sym_zero': 0.5,
 'adj_full': 1.0,
 'adj_zero': 4.0,
 'adj_credit': 1.0,
 'adj_glob_floor': 0.3,
 'glob_credit': 0.5,
 'far_full': 4.0,
 'far_zero': 12.0,
 'mirror_compact_floor': 0.6,
 'env_floor': 0.6,
 'dispersed_placement': 0.3,
 'orient_penalty_k': 3.0,
 'dummy_active_neighbour': 0.3,
 'dummy_diff_extension': 0.2,
 'dummy_search_pitches': 2.0,
 'dummy_missing_penalty': 0.15,
 'env_consistency_weight': 0.7,
 'env_well_clamp_um': 3.0,
 'env_well_d0_um': 0.5,
 'env_tap_clamp_um': 10.0,
 'env_tap_d0_um': 2.0,
 'coupling_rho0': 0.01,
 'protect_spacing_x': 3.0,
 'unprotected_cap': 0.6,
 'detour_free': 1.2,
 'detour_half': 0.5,
 'diff_d0': 0.03,
 'route_floor_um': 20.0,
 'mst_floor_um': 5.0,
 'route_tol_um': 10.0,
 'coupling_sub_weights': {'coupling': 0.4, 'routing': 0.3, 'diff_pairs': 0.3},
 'shield_fraction': 0.5,
 'power_min_current_a': 0.001,
 'ir_pct0': 0.5,
 'ir_dyn_pct0': 3.0,
 'em_penalty_k': 3.0,
 'power_sub_weights': {'width': 0.4, 'vias': 0.3, 'ir': 0.3},
 'power_conv': {'width_mult_zero': 2.0,
                'width_mult_full': 6.0,
                'trunk_zero': 0.5,
                'trunk_full': 0.95},
 'cpl_pen_max': 0.15,
 'cpl_pen_rho_full': 0.01,
 'grid_max_cells': 250000,
 'grid_min_pitch_um': 0.1,
 'default_supply_v': 1.8,
 'meaningless': {'bus_lines': 5,
                 'drops': 5,
                 'row_fraction': 0.7,
                 'row_elongation': 4.0,
                 'aux_fill': 0.4,
                 'line_dev_x': 3.0,
                 'hard_fill': 0.3,
                 'soft_fill': 0.5,
                 'aspect': 5.0,
                 'dispersed': 0.5,
                 'detour': 2.5,
                 'long_wire': 0.3,
                 'min_hits': 2,
                 'require_geometric': True}}
