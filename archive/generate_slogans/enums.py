from enum import Enum

class Mode(Enum):
    """
    Modes for parsing LaTeX papers for theorems.

    DEBUGGING (`debug`):
        No speed-ups, but prints out when parsing fails. By default, uses Langfuse. Does not
        update the RDS.
    
    PRODUCTION (`prod`):
        Generates slogans as fast as possible. Useful for sloganifying millions of theorems. By
        default, does not use Langfuse.
    """

    DEBUGGING = "debug"
    PRODUCTION = "prod"