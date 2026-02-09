import contextlib
import os
import sys
import logging

@contextlib.contextmanager
def use_plastex_log_capturer():
    """
    Context for capturing and hiding plasTeX logs.
    """

    logger_names = ("plasTeX", "plasTeX.TeX", "plasTeX.Packages", "plasTeX.DOM")

    # if mode == Mode.DEBUGGING:
    #     path = paper_dir / "DEBUG_plastex.log"
    #     path.parent.mkdir(parents=True, exist_ok=True)
    #     target_path = str(path)
    # else:
    target_path = os.devnull

    old_fd1 = os.dup(1)
    old_fd2 = os.dup(2)
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    prev = {}
    handler = None
    old_disable = logging.root.manager.disable

    try:
        f = open(target_path, "w", encoding="utf-8", errors="ignore")

        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)

        sys.stdout = f
        sys.stderr = f

        # handler = logging.StreamHandler(f) if mode == Mode.DEBUGGING else logging.NullHandler()
        handler = logging.NullHandler()

        for name in logger_names:
            lg = logging.getLogger(name)
            prev[name] = (lg.level, list(lg.handlers), lg.propagate)
            lg.handlers = [handler]
            lg.propagate = False
            # lg.setLevel(logging.DEBUG if mode == Mode.DEBUGGING else logging.CRITICAL)
            lg.setLevel(logging.CRITICAL)

        # logging.disable(logging.NOTSET if mode == Mode.DEBUGGING else logging.CRITICAL)
        logging.disable(logging.CRITICAL)

        yield
    finally:
        logging.disable(old_disable)

        for name, (lvl, hs, prop) in prev.items():
            lg = logging.getLogger(name)
            lg.setLevel(lvl)
            lg.handlers = hs
            lg.propagate = prop

        sys.stdout = old_stdout
        sys.stderr = old_stderr

        try:
            os.dup2(old_fd1, 1)
            os.dup2(old_fd2, 2)
        finally:
            os.close(old_fd1)
            os.close(old_fd2)

        if handler is not None and hasattr(handler, "close"):
            handler.close()

        try:
            f.close()
        except Exception:
            pass