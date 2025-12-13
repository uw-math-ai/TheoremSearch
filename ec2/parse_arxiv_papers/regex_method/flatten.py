import subprocess

def flatten_tex(
    main_tex_name: str, 
    src_dir: str,
    timeout: int
) -> str:
    proc = subprocess.run(
        [
            "latexdiff",
            "--flatten",
            main_tex_name,
            main_tex_name
        ],
        cwd=src_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )

    if proc.returncode != 0:
        raise RuntimeError("latexdiff failed")
    
    return proc.stdout