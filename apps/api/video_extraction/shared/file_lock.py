"""flock-compatible exclusive file locks for the engine's Windows and POSIX CLIs."""
import errno
import os
import time

LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8


def flock(file, operation):
    fd = file if isinstance(file, int) else file.fileno()
    if os.name != "nt":
        import fcntl
        return fcntl.flock(fd, operation)
    import msvcrt
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if operation & LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        mode = msvcrt.LK_NBLCK if operation & LOCK_EX else msvcrt.LK_NBRLCK
        while True:
            try:
                msvcrt.locking(fd, mode, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError(errno.EAGAIN, "Another engine process holds this lock") from None
                time.sleep(0.1)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
