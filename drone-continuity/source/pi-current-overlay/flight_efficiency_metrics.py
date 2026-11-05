"""Streaming DataFlash measurements for post-flight learning, never control writes.

BAT Volt/Curr are volts/amps and ATT angles are degrees. Missing current is
not estimated from throttle or voltage. Energy covers measured intervals only.
"""
import math
import numbers


def number(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    value = float(value)
    return value if math.isfinite(value) and lower <= value <= upper else None


class FlightEfficiencyMetrics:
    def __init__(self):
        self.batteries = {}
        self.errors = {axis: {'samples': 0, 'sum_squared_deg': 0., 'maximum_abs_deg': 0.}
                       for axis in ('Roll', 'Pitch', 'Yaw')}

    def observe(self, kind, values):
        if kind == 'BAT':
            instance = values.get('Inst')
            if type(instance) is not int or not 0 <= instance <= 8:
                return  # Never combine unidentified battery monitors.
            state = self.batteries.setdefault(instance, {
                'voltage_samples': 0, 'voltage_sum_v': 0., 'minimum_voltage_v': None,
                'current_samples': 0, 'current_sum_a': 0., 'peak_current_a': None,
                'measured_energy_wh': 0., 'measured_charge_mah': 0.,
                'measured_interval_seconds': 0., 'integrated_intervals': 0,
                'rejected_intervals': 0, 'previous': None,
            })
            health = values.get('H')
            if type(health) not in (bool, int) or health != 1:
                # Older logs without H retain unknown health; never turn an
                # absent/foreign/string field into measured healthy energy.
                state['previous'] = None
                state['rejected_intervals'] += 1
                return
            volts = number(values.get('Volt'), 0.001, 100)
            amps = number(values.get('Curr'), 0, 1000)
            stamp = number(values.get('TimeUS'), 0, 1e16)
            if volts is not None:
                state['voltage_samples'] += 1
                state['voltage_sum_v'] += volts
                state['minimum_voltage_v'] = min(volts, state['minimum_voltage_v'] or volts)
            if amps is not None:
                state['current_samples'] += 1
                state['current_sum_a'] += amps
                state['peak_current_a'] = max(amps, state['peak_current_a'] or 0)
            if None in (volts, amps, stamp):
                state['previous'] = None
                state['rejected_intervals'] += 1
                return
            previous = state['previous']
            if previous is not None:
                old_stamp, old_volts, old_amps = previous
                seconds = (stamp - old_stamp) / 1e6
                if 0 < seconds <= 10:
                    state['measured_energy_wh'] += (old_volts * old_amps + volts * amps) * seconds / 7200
                    state['measured_charge_mah'] += (old_amps + amps) * seconds / 7.2
                    state['measured_interval_seconds'] += seconds
                    state['integrated_intervals'] += 1
                else:
                    state['rejected_intervals'] += 1
            state['previous'] = (stamp, volts, amps)
        elif kind == 'ATT':
            for axis, state in self.errors.items():
                actual = number(values.get(axis), -360, 360)
                desired = number(values.get('Des' + axis), -360, 360)
                if actual is None or desired is None:
                    continue
                difference = (actual - desired + 180) % 360 - 180
                state['samples'] += 1
                state['sum_squared_deg'] += difference * difference
                state['maximum_abs_deg'] = max(state['maximum_abs_deg'], abs(difference))

    def report(self):
        batteries = {}
        for instance, state in sorted(self.batteries.items()):
            report = {key: value for key, value in state.items()
                      if key not in ('previous', 'voltage_sum_v', 'current_sum_a')}
            report['mean_sampled_voltage_v'] = (state['voltage_sum_v'] / state['voltage_samples']
                                                if state['voltage_samples'] else None)
            report['mean_sampled_current_a'] = (state['current_sum_a'] / state['current_samples']
                                               if state['current_samples'] else None)
            report['mean_measured_power_w'] = (state['measured_energy_wh'] * 3600 / state['measured_interval_seconds']
                                              if state['measured_interval_seconds'] else None)
            report['energy_valid'] = state['integrated_intervals'] > 0
            batteries[str(instance)] = report
        tracking = {axis.lower(): {
            'samples': state['samples'],
            'rmse_deg': math.sqrt(state['sum_squared_deg'] / state['samples']) if state['samples'] else None,
            'maximum_abs_error_deg': state['maximum_abs_deg'] if state['samples'] else None,
        } for axis, state in self.errors.items()}
        return {
            'schema': 1, 'authority': 'post_flight_measurements_only',
            'batteries': batteries, 'attitude_tracking': tracking,
            'learned_battery_saving_mode_enabled': False,
            'may_write_ardupilot_parameters': False, 'may_command_actuators': False,
            'qualification': 'Requires calibrated battery monitoring, battery/build identity, matched conditions, whole-flight holdout and human review before a learned-mode proposal.',
            'limitations': [
                'Measurements include ground and flight samples; not an airborne-only efficiency estimate.',
                'Energy is only the integral of valid intervals, not guaranteed full-flight consumption.',
                'Sampled voltage variation does not establish battery health, remaining capacity or safe reserve.',
                'Tracking error does not establish stability, crash avoidance or a safe PID/control update.',
            ],
        }
