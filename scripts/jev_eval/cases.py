"""Entrevistas sintéticas independientes del audio de diagnóstico.

Cada turno contiene la etiqueta observada, el texto y, cuando difiere, la voz real.
P es paciente, E entrevistador y X otro interlocutor. None indica voz no asignada.
Las etiquetas gold apuntan a índices de turnos actuales, empezando en cero.
"""


def case(name, turns, gold=None, *, previous=(), roles=None, diagnostic=False):
    return {
        "id": name, "turns": turns, "previous": previous, "gold": gold or {},
        "roles": {"P": "patient", "E": "professional", "X": "professional"} if roles is None else roles,
        "diagnostic": diagnostic,
    }


CASES = [
    case("malestar_directo", [("P", "Me siento triste todo el día y estoy agotada.")], {0: [0]}),
    case("malestar_indirecto", [("E", "¿Cómo van tus mañanas?"), ("P", "Se me hace cuesta arriba hasta levantarme de la cama.")], {0: [1]}),
    case("malestar_y_negacion", [("P", "Estoy angustiada y no duermo. Nunca he pensado en quitarme la vida.")], {0: [0]}),
    case("dormir_para_descansar", [("P", "Quiero dormir todo el día, estoy rendida. Mañana quiero levantarme temprano.")], {0: [0]}),
    case("irse_del_trabajo", [("P", "Me supera el trabajo. No quiero seguir acá, voy a renunciar.")], {0: [0]}),
    case("desaparecer_social", [("P", "Quisiera desaparecer un tiempo de los chats. Me abruma todo.")], {0: [0]}),
    case("malestar_si", [("E", "¿Te has sentido muy triste estos días?"), ("P", "Sí, todos los días.")], {0: [1]}),
    case("malestar_entrevistador", [("E", "A veces digo ‘me siento horrible’ para ilustrar cómo suena la angustia."), ("P", "Entiendo el ejemplo.")]),
    case("pasivo_explicito", [("P", "Ojalá estuviera muerta.")], {1: [0]}),
    case("pasivo_no_despertar", [("P", "Me gustaría quedarme dormida para siempre.")], {1: [0]}),
    case("pasivo_indirecto", [("E", "¿Qué significa para ti que todo se apague?"), ("P", "Acostarme y que para mí ya no haya mañana, que la vida se termine sola.")], {1: [1]}),
    case("pasivo_con_negacion_activa", [("P", "Ojalá no despertara. Nunca he pensado en matarme.")], {1: [0]}),
    case("pasivo_si", [("E", "¿Has deseado estar muerta esta semana?"), ("P", "Sí.")], {1: [1]}),
    case("pasivo_si_cruce", [("P", "Sí, eso me pasa.")], {1: [0]}, previous=[("E", "¿Deseas no despertar cuando te acuestas?")]),
    case("pasivo_cruce_con_interjeccion", [("P", "Sí, lo he deseado.")], {1: [0]},
         previous=[("E", "¿Has deseado que tu vida termine por sí sola?"), ("E", "Tómate tu tiempo.")]),
    case("pasivo_antecedente_ajeno_a_frase", [("P", "Mi hermana llamó ayer, pero soy yo la que desearía estar muerta.")], {1: [0]}),
    case("pasivo_cita_propia_actual", [("P", 'Anoche dije "ojalá no despierte" y hoy sigo sintiendo lo mismo.')], {1: [0]}),
    case("pasivo_pro_pregunta_ajena", [("E", "Si digo ‘preferiría morirme’, te estoy mostrando cómo preguntar."), ("P", "Comprendo.")]),
    case("pasivo_negacion", [("P", "No quiero morirme. Estoy bien y tengo ganas de vivir.")]),
    case("pasivo_anterior_no_reemitir", [("E", "Pasemos a tu rutina."), ("P", "Desayuné temprano.")],
         previous=[("P", "Ojalá no despertara.")]),
    case("activo_explicito", [("P", "Estos días he pensado en suicidarme.")], {2: [0]}),
    case("activo_indirecto", [("E", "¿Qué quieres decir con ponerle fin?"), ("P", "Que he pensado en acabar yo misma con mi vida.")], {2: [1]}),
    case("activo_indirecto_reformulacion", [("P", "Me pasa por la cabeza terminar yo con todo."), ("E", "¿Quitar tú misma tu vida?"), ("P", "Exacto, a eso me refiero.")], {2: [2]}),
    case("activo_si", [("E", "¿Has pensado en quitarte la vida?"), ("P", "Sí, lo he pensado.")], {2: [1]}),
    case("activo_si_cruce", [("P", "Sí, varias veces.")], {2: [0]}, previous=[("E", "¿Has pensado en matarte?")]),
    case("activo_corte_incompleto", [("P", "…cómo hacerlo." )], previous=[("E", "¿Quieres que revisemos lo del trabajo?"), (None, "Cuando pienso en…")]),
    case("activo_no_cruce", [("P", "No, nunca.")], previous=[("E", "¿Has pensado en suicidarte?")]),
    case("activo_si_compuesta", [("E", "¿Pensaste en matarte o solo necesitabas descansar?"), ("P", "Sí.")]),
    case("activo_si_compuesta_cruce", [("P", "Sí, supongo.")], previous=[("E", "¿Pensaste en matarte o en irte de viaje?")]),
    case("activo_si_facilitador", [("E", "A veces pregunto si has pensado en matarte. ¿Se entiende la pregunta?"), ("P", "Sí, se entiende.")]),
    case("activo_negado", [("E", "¿Has pensado en suicidarte?"), ("P", "No, nunca he pensado en suicidarme.")]),
    case("activo_negado_tras_pausa", [("P", "Pensé en quitarme la vida…"), ("P", "No, corrijo, pensé en irme de casa, jamás en matarme.")]),
    case("activo_cita_ajena", [("P", 'En la obra mi personaje dice "pienso en quitarme la vida". Solo era el libreto.')]),
    case("activo_tercero", [("P", "Mi hermano me contó que piensa en suicidarse.")]),
    case("activo_pasado_resuelto", [("P", "Hace años pensaba en quitarme la vida. Hoy no tengo esos pensamientos.")]),
    case("activo_ejemplo_entrevistador", [("E", "Como ejemplo, digo: he pensado en quitarme la vida."), ("P", "Ah, ahora entiendo la diferencia.")]),
    case("activo_pregunta_entrevistador_solo", [("E", "¿Te has imaginado acabar con tu vida?")]),
    case("activo_voz_desconocida", [(None, "Pienso en matarme.", "P")], {2: [0]}),
    case("activo_paciente_mal_etiquetada", [("E", "¿Cómo has estado?"), ("E", "He pensado en matarme.", "P")], {2: [1]}),
    case("activo_profesional_mal_etiquetado", [("E", "Voy a leer en voz alta una frase de ejemplo."), ("P", "Últimamente pienso en matarme.", "E"), ("P", "Ya entendí lo que leíste.")]),
    case("activo_roles_diagnostico", [("E", "Quiero entender lo que te está pasando."), ("P", "En serio, estoy pensando en quitarme la vida.")], {2: [1]}, roles={}, diagnostic=True),
    case("pasivo_roles_diagnostico", [("P", "No me importaría que la vida se me apagara sola."), ("E", "¿Y cada cuánto aparece ese deseo?"), ("P", "Casi todas las noches.")], {1: [0]}, roles={}, diagnostic=True),
    case("diagnostico_profesional_ejemplo", [("E", "Pongamos un ejemplo. Yo digo que pienso en suicidarme."), ("P", "No, nada que ver con lo mío.")], roles={}, diagnostic=True),
    case("activo_rol_clinico_no_confirmado", [("E", "Cuéntame qué te pasa."), ("P", "Estoy pensando en suicidarme.")], {2: [1]}, roles={"E": "professional"}),
    case("dos_categorias", [("P", "Desearía no despertar. A veces también pienso en quitarme la vida.")], {1: [0], 2: [0]}),
    case("pasivo_voz_superpuesta", [("P", "Ojalá estuviera muerta."), ("E", "Un momento, espera.")], {1: [0]}),
]


# Segunda batería escrita para comprobar la variante de respuesta previa.
EXTENSION_CASES = [
    case("previa_pasivo_afirmacion", [("P", "Sí, algunas noches.")], {1: [0]},
         previous=[("E", "¿Has deseado que tu vida acabe por sí sola?")]),
    case("previa_pasivo_asiente", [("P", "Exacto, me pasa al acostarme.")], {1: [0]},
         previous=[("E", "¿Lo que quieres es dormir y no volver a despertar?")]),
    case("previa_activo_afirmacion", [("P", "Sí, me ha pasado dos veces.")], {2: [0]},
         previous=[("E", "¿Has pensado en causarte tu propia muerte?")]),
    case("previa_activo_invitacion", [("P", "Así es. Es algo que he pensado.")], {2: [0]},
         previous=[("E", "¿Has pensado en quitarte la vida?"), ("E", "Te escucho.")]),
    case("previa_malestar", [("P", "Sí, casi todos los días.")], {0: [0]},
         previous=[("E", "¿Te sientes abrumada al despertar?")]),
    case("previa_negacion_pasiva", [("P", "No, eso nunca lo he deseado.")],
         previous=[("E", "¿Has deseado no despertar?")]),
    case("previa_negacion_activa", [("P", "Nunca he pensado en eso.")],
         previous=[("E", "¿Has pensado en matarte?")]),
    case("previa_dos_opciones", [("P", "Sí, eso.")],
         previous=[("E", "¿Has pensado en suicidarte o en cambiarte de casa?")]),
    case("previa_menciona_ejemplo", [("P", "Sí, se entiende el ejemplo.")],
         previous=[("E", "Si alguien dice que quiere suicidarse, es un ejemplo. ¿Se entiende?")]),
    case("previa_solo_paciente", [("P", "Sí, el trámite lo hice hoy.")],
         previous=[("P", "¿Por qué a veces pienso en matarme?")]),
    case("previa_sin_confirmacion_del_rol", [("P", "Sí, últimamente.")], {2: [0]},
         previous=[("E", "¿Has pensado en quitarte la vida?")], roles={"E": "professional"}),
    case("previa_paciente_sin_si", [("P", "La última vez que pensé eso fue hoy.")], {2: [0]},
         previous=[("E", "¿Has pensado en acabar con tu vida?")]),
    case("previa_senal_no_reemitida", [("P", "Sí, la probé ayer y me sirvió.")],
         previous=[("P", "Pensé en quitarme la vida."), ("E", "¿Probaste la técnica de respiración?")]),
    case("previa_riesgo_independiente", [("P", "Me gustaría no volver a despertar.")], {1: [0]},
         previous=[("E", "¿Cómo te has sentido hoy?")]),
]
