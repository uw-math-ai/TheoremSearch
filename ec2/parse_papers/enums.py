from enum import Enum

class Mode(Enum):
    """
    Modes for parsing LaTeX papers for theorems.

    DEBUGGING (`debug`):
        Prints out lots of helpful logs including errors and when major functions fail. Generates
        helpful files to inspect in the `debug` folder. Has no side effects (doesn't update RDS)
        nor uses speed-ups. Halts the pipeline on errors. Useful for debugging the parser on one
        troublesome paper

    DEVELOPMENT (`dev`):
        Prints out some helpful logs giving a general error for when a paper fails to parse.
        Updates the RDS but has no speed-ups. Useful for parsing papers with some monitoring
    
    PRODUCTION (`prod`):
        Parses papers as fast as possible. Useful for parsing hundreds of thousands of papers
    """

    DEBUGGING = "debug"
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"

class Method(Enum):
    """
    Methods for attempting to parse theorems from a LaTeX source. Supported: PLASTEX, TEX, and
    REGEX.
    """

    PLASTEX = "plastex"
    TEX = "tex"
    REGEX = "regex"

class ArXivPaperSource(Enum):
    """
    Sources for downloading papers. Supported: S3 and API
    """

    S3 = "s3"
    API = "api"

class TheoremValidationLevel(Enum):
    """
    Level to check if parsed theorems are valid.
    """

    THEOREM = "theorem"
    PAPER = "paper"