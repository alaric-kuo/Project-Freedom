import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# ==========================================
# 0. Global Visual Settings
# ==========================================
# Scenario color coding: 
# c311: Historical failure (Red)
# cNow: Modern defense success (Green)
# cDoom: Extreme M9.5 scenario (Purple)
# cRef: Baseline/Reference (Grey)
c311 = '#e74c3c'   
cNow = '#27ae60'   
cDoom = '#8e44ad'  
cRef = '#7f8c8d'   

plt.style.use('default') 

# ==========================================
# 1. Alaric RPG Model: Deep Physics Kernel
# ==========================================
class ReactorState:
    """
    Core Engine for the Risk Physics & Governance (RPG) Model.
    Simulates the dynamic decay of structural integrity based on energy balance.
    """
    def __init__(self, v_impact=0):
        # Physical State Variables
        self.zeta = 3500.0        # Reactor Water Level [mm] (Ref: TAF=0)
        self.core_integrity = 100.0 
        self.rpv_integrity = 100.0  
        self.heat_accum = 0.0     # Accumulated residual heat energy
        self.v = v_impact         # Tsunami kinetic potential [m] overtopping the wall
        
        # Calibration Constants (Benchmarked against 3.11 Daiichi Unit 1)
        self.decay_base = 100.0   # Initial decay heat power
        self.boil_rate = 5.8      # Rate of water inventory loss per heat unit
        self.melt_rate = 0.9       # Rate of core degradation post-exposure
        self.melt_through_rate = 0.12 # RPV breach progression rate
        
    def update(self, dt_min, time_since_scram, status):
        """
        Physics Update Loop: Calculates the transition between steady state and collapse.
        """
        # 1. Decay Heat Calculation: Power law based on time since reactor shutdown
        t_val = max(time_since_scram, 1.0) if time_since_scram else 1.0
        decay_heat = self.decay_base * (t_val**(-0.2))
        
        # 2. Active Cooling Logic
        cooling = 0
        if status['active']: 
            cooling = decay_heat * 1.15 # Active cooling exceeds decay heat (Stable)
        elif status['emergency']: 
            cooling = decay_heat * 0.1  # Residual/Emergency cooling (Insufficient)
        
        # 3. Energy Inversion (Delta P): The 'Meaning Layer'
        # Calculates if the system is gaining or losing energy balance.
        # [Alaric Note] Impact load represents the dynamic pressure of overtopping water.
        impact_load = 0
        if not status['active']:
            impact_load = (self.v ** 1.6) * 0.5 # 1.6 power law for debris-mixed fluid impact
        
        delta_p = cooling - (decay_heat + impact_load)
        
        d_zeta_dt = 0; d_core_dt = 0; d_rpv_dt = 0
        
        # 4. The 'Calculation Layer': Structural Decay Dynamics
        if delta_p < 0:
            # System has entered an irreversible energy deficit
            self.heat_accum += abs(delta_p) * dt_min
            
            # term_a: Internal Entropy Stress (Internal boiling and pressure buildup)
            term_a = (self.heat_accum * 0.008) * self.boil_rate
            
            # term_v: External Kinetic Stress (Tsunami momentum and structural damage)
            term_v = 0
            if not status['active']:
                # The 1.6 exponent represents non-linear environmental stress (Debris/Turbulence)
                term_v = (self.v ** 1.6) * 4.5
            
            # Coupling Term: 'Destructive Resonance'
            # Represents the multiplicative effect of internal heat and external impact.
            # (e.g., Thermal stress weakening pipes while vibration causes fracture).
            coupling = (term_a * term_v) * 0.02
            
            # Rate of water level decay (Collapse Slope)
            d_zeta_dt -= (term_a + term_v + coupling) * dt_min
            
        else:
            # System is stable; cooling is removing accumulated heat
            self.heat_accum = max(0, self.heat_accum - delta_p * dt_min)
            
        # 5. Integrity Phase Transitions
        if self.zeta <= 0: 
            d_core_dt = -self.melt_rate * dt_min # Core begins to melt after TAF exposure
        if self.core_integrity < 20: 
            d_rpv_dt = -self.melt_through_rate * dt_min # Molten fuel breaches the RPV

        self.zeta += d_zeta_dt
        self.core_integrity = max(0, self.core_integrity + d_core_dt)
        self.rpv_integrity = max(0, self.rpv_integrity + d_rpv_dt)
        
        # 6. Alaric Term: The 'Event Horizon' Indicator
        # Normalized relative collapse rate: (1/m)(dm/dt)
        # Scaled by 500,000 for visualization of the 'Decay Canyon' in FIG 3.
        current_mass = max(self.zeta + 100, 10.0)
        base_term = (d_zeta_dt + d_core_dt * 20) / current_mass
        alaric_term = base_term * 500000.0 
        
        return self.zeta, self.core_integrity, self.rpv_integrity, delta_p, alaric_term

def simulate(wall_h, tsunami_h, events):
    """
    Time-series simulation runner for different disaster scenarios.
    """
    times = pd.date_range(start="2011-03-11 14:00", end="2011-03-12 12:00", freq="10min")
    v = max(0, tsunami_h - wall_h) # Effective overtopping height
    reactor = ReactorState(v_impact=v)
    data = []
    status = {'active': True, 'emergency': False}
    t_scram = None
    
    for t in times:
        # Event Triggering Logic
        if t >= events['quake'] and t_scram is None: t_scram = 1.0
        if t >= events['tsunami']:
            if tsunami_h > wall_h: # Tsunami breaches the sea wall
                status['active'] = False; status['emergency'] = True
                # SBO (Station Blackout) occurs after emergency power is flooded
                if t >= events['tsunami'] + timedelta(hours=8): status['emergency'] = False
            
        if t_scram: t_scram += 10 # Step time forward for decay heat curve
        z, c, r, dp, al = reactor.update(10, t_scram, status)
        data.append({'time': t, 'zeta': z, 'core': c, 'rpv': r, 'dp': dp, 'alaric': al})
    return pd.DataFrame(data)

# --- Historical Benchmarks (Fukushima Daiichi Unit 1) ---
hist = {
    'quake': pd.Timestamp("2011-03-11 14:46"),
    'tsunami_warn': pd.Timestamp("2011-03-11 14:50"),
    'tsunami': pd.Timestamp("2011-03-11 15:37"),
    'taf_exposure': pd.Timestamp("2011-03-11 18:10"),
    'meltdown_start': pd.Timestamp("2011-03-11 19:30"),
    'sensor_alert': pd.Timestamp("2011-03-11 20:07"),
    'rpv_fail': pd.Timestamp("2011-03-12 07:00")
}

# Run Three Worldlines
df_past = simulate(5.7, 14.0, hist)       # Reality: Insufficient wall
df_now = simulate(15.0, 14.0, hist)        # Success: Modern wall withstands M9.0
df_doom = simulate(15.0, 25.0, hist)       # Future: Wall breached by extreme M9.5

# Calculate the Alaric Alert point (Moment of Energy Inversion)
alaric_alert_311 = df_past[df_past['dp'] < 0].iloc[0]['time']

# ==========================================
# FIG 1: Survival Layer (Structural Integrity)
# ==========================================

plt.figure(figsize=(12, 6))
ax = plt.gca()
ax.axhspan(-4000, 0, color='red', alpha=0.05, label='Meltdown Zone')

plt.plot(df_past['time'], df_past['zeta'], color=c311, label='3.11 Reality (Failure)', linewidth=2)
plt.plot(df_now['time'], df_now['zeta'], color=cNow, label='Current Measures vs M9.0 (Success)', linewidth=4)
plt.plot(df_doom['time'], df_doom['zeta'], color=cDoom, linestyle='--', label='Future M9.5 Trend')
plt.axhline(0, color='black', linewidth=1)
plt.title('FIG 1: SURVIVAL LAYER - Structural Integrity & RPV Window', fontweight='bold', fontsize=14)
plt.ylabel('Water Level [mm] (TAF=0)')
plt.ylim(-3000, 4000)

plt.annotate('Tsunami Warning\n(14:50)', xy=(hist['tsunami_warn'], 3500), color='blue', fontweight='bold', 
             xytext=(hist['tsunami_warn'], 4200), arrowprops=dict(arrowstyle='->', color='blue'))

plt.annotate('RPV Failure\n(3/12 06:00)', xy=(hist['rpv_fail'], 0), color='black', fontweight='bold', 
             xytext=(hist['rpv_fail']-timedelta(hours=6), -2000), arrowprops=dict(arrowstyle='->'))

plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
plt.legend(loc='upper right'); plt.grid(True, alpha=0.3); plt.tight_layout(); plt.show()

# ==========================================
# FIG 2: Decision Layer (Energy Inversion)
# ==========================================

plt.figure(figsize=(12, 6))
plt.plot(df_past['time'], df_past['dp'], color=c311, label='311 Energy Gradient', linewidth=2)
plt.plot(df_now['time'], df_now['dp'], color=cNow, label='Current Stability Trend', linewidth=4)
plt.plot(df_doom['time'], df_doom['dp'], color=cDoom, linestyle='--', label='Future M9.5 Trend') 
plt.axhline(0, color='black', linewidth=1)
plt.title('FIG 2: DECISION LAYER - Energy Inversion & Warning Gap', fontweight='bold', fontsize=14)
plt.ylabel('Energy Gradient [Delta P]')

plt.annotate(f'Alaric Alert (Inversion)\n{alaric_alert_311.strftime("%H:%M")}', xy=(alaric_alert_311, 0), color='red', fontweight='bold', 
             xytext=(alaric_alert_311-timedelta(hours=4), 35), arrowprops=dict(arrowstyle='->', color='red'))
plt.annotate('Traditional Sensor Alert\n(20:07)', xy=(hist['sensor_alert'], 0), color='gray', fontweight='bold', 
             xytext=(hist['sensor_alert']+timedelta(hours=2), -50), arrowprops=dict(arrowstyle='->', color='gray'))

plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout(); plt.show()

# ==========================================
# FIG 3: Physics Layer (Decay Canyon)
# ==========================================

plt.figure(figsize=(12, 6))
plt.plot(df_past['time'], df_past['alaric'], color=c311, label='311 Structural Decay Rate', linewidth=2)
plt.plot(df_now['time'], df_now['alaric'], color=cNow, label='Current Stability Trend', linewidth=4)
plt.plot(df_doom['time'], df_doom['alaric'], color=cDoom, linestyle='--', label='Future M9.5 Decay Trend')

# The Y-Axis is inverted to visualize the 'Abyss' of systemic collapse.
plt.gca().invert_yaxis()

plt.title('FIG 3: PHYSICS LAYER - Sequential Collapse Progression', fontweight='bold', fontsize=14)
plt.ylabel('Decay Index (1/m)(dm/dt) * Scaled')

# Mapping key disaster milestones to the Decay Index
plt.annotate('Wall Breach (15:37)', xy=(hist['tsunami'], 0), color='black', fontweight='bold', 
             xytext=(hist['tsunami']-timedelta(hours=3), -500000000), arrowprops=dict(arrowstyle='->'))
plt.annotate('Fuel Exposure (18:10)', xy=(hist['taf_exposure'], -500), color='red', fontweight='bold', 
             xytext=(hist['taf_exposure']-timedelta(minutes=30), -500000000), arrowprops=dict(arrowstyle='->', color='red'))
plt.annotate('Core Meltdown (19:30)', xy=(hist['meltdown_start'], -2000), color='darkred', fontweight='bold', 
             xytext=(hist['meltdown_start']+timedelta(hours=2), -500000000), arrowprops=dict(arrowstyle='->', color='darkred'))
plt.annotate('RPV Failure (3/12 07:00)', xy=(hist['rpv_fail'], -5000), color='black', fontweight='bold', 
             xytext=(hist['rpv_fail']-timedelta(hours=6), -500000000), arrowprops=dict(arrowstyle='->'))

plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout(); plt.show()