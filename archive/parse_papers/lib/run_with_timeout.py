from multiprocessing import Process, Queue
import queue as queue_mod

def run_with_timeout(seconds: int):
    """
    Decorator that runs a function with a timeout.

    Parameters
    ----------
    seconds : int
        Number of seconds to allow a function to run
    """

    def handler(queue, func, args, kwargs):
        try:
            queue.put(("ok", func(*args, **kwargs)))
        except BaseException as e:
            queue.put(("err", (type(e).__name__, str(e))))

    def decorator(func):
        def wraps(*args, **kwargs):
            q = Queue()
            p = Process(target=handler, args=(q, func, args, kwargs))
            p.start()
            p.join(timeout=seconds)

            if p.is_alive():
                p.terminate()
                p.join()
                raise TimeoutError(f"Timeout (> {seconds} seconds)")
            else:
                try:
                    tag, payload = q.get_nowait()
                except queue_mod.Empty:
                    raise RuntimeError("Child process exited without returning")

                if tag == "err":
                    _, msg = payload
                    raise RuntimeError(msg)

                return payload

        return wraps

    return decorator