"""Bloqueos y publicación durable de archivos en POSIX y Windows."""
import errno
import os
import stat
from pathlib import Path

from django.core.files import locks


def private_directory(path):
    """Restringir también directorios existentes antes de escribir audio."""
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return

    import ctypes
    from ctypes import wintypes

    security = ctypes.WinDLL("advapi32", use_last_error=True)
    descriptor, acl = ctypes.c_void_p(), ctypes.c_void_p()
    present, defaulted = wintypes.BOOL(), wintypes.BOOL()
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_acl = security.GetSecurityDescriptorDacl
    get_acl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_acl.restype = wintypes.BOOL
    set_acl = security.SetNamedSecurityInfoW
    set_acl.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_acl.restype = wintypes.DWORD
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p

    # ACL protegida y heredable: sistema, administradores y propietario.
    if not convert("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)",
                   1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not get_acl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        # SE_FILE_OBJECT; DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        error = set_acl(str(path.absolute()), 1, 0x80000004, None, None, acl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        free(descriptor)


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
    if flags & os.O_CREAT:
        # CREATE_NEW, CREATE_ALWAYS u OPEN_ALWAYS.
        disposition = 1 if flags & os.O_EXCL else (2 if flags & os.O_TRUNC else 4)
    else:
        # TRUNCATE_EXISTING u OPEN_EXISTING.
        disposition = 5 if flags & os.O_TRUNC else 3
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
