from typing import TypedDict, List

class SloganModel(TypedDict):
    """
    A Dict representation of a slogan-generating LLM model available on AWS Bedrock.

    Fields
    ------
    id : str
        The AWS Bedrock id of the model
    input_token_cost : float
        The reported cost per input token in USD
    output_token_cost : float
        The reported cost per output token in USD
    """

    id: str
    input_token_cost: float
    output_token_cost: float

class SloganPrompt(TypedDict):
    """
    A Dict representation of a prompt given to a SloganModel to generate slogans

    Fields
    ------
    id : str
        An ID describing what this prompt is e.g. `body-only-v1`
    instructions : str
        General instructions for the LLM to generate slogans
    context : List[str]
        List of column names in `paper` or `theorem`
    temperature : float
        The LLM model's temperature
    max_tokens : int
        The LLM models' maximum output tokens
    """

    id: str
    instructions: str
    context: List[str]
    temperature: float
    max_tokens: int
