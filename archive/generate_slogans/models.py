from typing import TypedDict, Dict
from .types import SloganModel

"""
Available AWS Bedrock LLM models for slogan generation.
"""
MODELS: Dict[str, SloganModel] = {
    "DeepSeek-R1": {
        "id": "us.deepseek.r1-v1:0",
        "input_token_cost": 0.00135 / 1000,
        "output_token_cost": 0.0054 / 1000
    },
    "DeepSeek-V3.1": {
        "id": "deepseek.v3-v1:0",
        "input_token_cost": 0.00058 / 1000,
        "output_token_cost": 0.00168 / 1000
    }
}