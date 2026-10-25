"""Bloqueos y publicación durable de archivos en POSIX y Windows."""
import errno
import os
import stat
from pathlib import Path

from django.core.files import locks


def lock_file(file, *, exclusive=True, blocking=True):
    flags = locks.LOCK_EX if exclusive else locks.LOCK_SH
    if not blocking:
        flags |= locks.LOCK_NB
    # Django usa flock en POSIX y LockFileEx en Windows. Nunca continuar
    # sin un bloqueo, incluso si el sistema de archivos no lo soporta.
    if not locks.lock(file, flags):
        raise BlockingIOError(errno.EAGAIN, "Bloqueo de archivo no disponible.")


def open_private(path, flags):
    """Abrir un archivo regular sin seguir enlaces ni puntos de reanálisis."""
    if os.name == "nt":
        fd = _open_windows(path, flags)
    else:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError(errno.EINVAL, "Se requiere un archivo regular.")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_windows(path, flags):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    disposition = 1 if flags & os.O_EXCL else (4 if flags & os.O_CREAT else 3)
    # GENERIC_READ | GENERIC_WRITE; FILE_SHARE_READ | FILE_SHARE_WRITE.
    # OPEN_REPARSE_POINT abre el enlace mismo para rechazarlo con fstat.
    handle = create(str(Path(path).absolute()), 0xC0000000, 0x3, None,
                    disposition, 0x00200080, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        close(handle)
        raise


def publish_file(source, destination):
    """El llamador cierra el archivo y conserva el bloqueo de asignación."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        # MOVEFILE_WRITE_THROUGH; no reemplazar un destino existente.
        if not move(str(Path(source).absolute()), str(Path(destination).absolute()), 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        # link falla si el destino ya existe; nunca sobrescribir otro blob.
        os.link(source, destination, follow_symlinks=False)
        os.unlink(source)
        directory = os.open(Path(destination).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
