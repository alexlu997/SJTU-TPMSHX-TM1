"""Temperature offset for conversions between Celsius and kelvin."""
from tm1.model_configs.model_parameters import load_model_parameters


CELSIUS_ZERO_K: float = load_model_parameters()['constants']['celsius_zero_K']
