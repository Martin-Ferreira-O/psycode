#!/usr/bin/env python
"""Punto de entrada Django, ejecutado desde la raíz del repositorio."""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
