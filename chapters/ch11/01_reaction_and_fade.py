"""Chapter 11, price reaction and fading a rumor: made-up prices and beliefs."""
from polymarket_strategies.reaction import fade_value, implied_chance_true, reaction

summary = reaction([(0, 0.40), (60, 0.60), (300, 0.50), (3600, 0.45)], release=0)
print({key: ({k: (round(v, 4) if isinstance(v, float) else v) for k, v in value.items()} if isinstance(value, dict) else value)
       for key, value in summary.items()})  # rounded: no float noise
print({"implied_rumor_probability": round(implied_chance_true(0.40, 0.60), 4),
       "fade_value_before_costs": round(fade_value(0.40, 0.60, belief_true=0.20), 4)})
print("Time samples and personal beliefs do not demonstrate executable fills or a repeatable edge.")

