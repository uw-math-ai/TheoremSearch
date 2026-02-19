from typing import Dict, Any

def print_script_header(
    action: str,
    params: Dict[str, Any]
):
    """
    Prints a formatted script header that tells a user what's about to be run.

    Parameters
    ----------
    action : str
        A short description of what the following script does
    params : Dict[str, Any]
        All relevant parameters that define how the script is run. If a parameter ending in a `?`
        has a falsy value, does not print that parameters
    """

    action = f"=== {action} ==="

    print(action)

    for param, value in params.items():
        if param.endswith("?") and not value:
            continue

        print(f"  > {param.removesuffix('?')}:", value)

    print("=" * len(action))