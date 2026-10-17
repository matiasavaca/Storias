"""Tests del motor de contenido multi-cliente.

Los fixtures reproducen los valores reales de CUAN (personaje, 6 ejemplos
de tono, 10 temas) para documentar que la migracion preserva el
comportamiento original. La API de Claude y Cloudinary se mockean: no se
gasta credito real.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image

from app.engine import content
from app.engine.content import (
    CLAUDE_MODEL,
    TEMA_FALLBACK,
    _armar_prompt,
    _elegir_tema,
)
from app.engine.exceptions import EngineError, MetaPublishError
from app.engine.schemas import (
    ClientContentConfig,
    HiloGenerado,
    ImagenCandidata,
    ResultadoPublicacion,
)

# ---------------------------------------------------------------------------
# Fixtures: valores reales de CUAN del main.py original
# ---------------------------------------------------------------------------

BUSINESS_DESCRIPTION_CUAN = (
    "Sos el copywriter de CUAN, un estudio que diseña cocinas "
    "a medida para personas que están construyendo o remodelando "
    "su casa. Tu público NO son arquitectos ni diseñadores: son "
    "personas comunes armando su casa, muchas veces por primera vez."
)

TONE_EXAMPLES_CUAN = [
    [
        "El error más caro de una cocina no es la mesada.",
        "Es construir algo que después no funciona.",
        "Por eso diseñamos todo en 3D antes de la obra.",
        "¿Pensás renovar tu cocina? Escribí COCINA.",
    ],
    [
        "¿Tu cocina se siente chica?",
        "Muchas veces no faltan metros.",
        "Falta una mejor distribución.",
        "Mandá DISEÑO y te mostramos posibilidades.",
    ],
    [
        "La mayoría elige materiales demasiado pronto.",
        "Y se olvida de lo más importante.",
        "La distribución.",
        "Escribí PLAN y te contamos cómo trabajamos.",
    ],
    [
        "¿Querés una isla?",
        "No siempre es la mejor solución.",
        "Cada cocina necesita una estrategia distinta.",
        "Mandá PROYECTO y lo vemos juntos.",
    ],
    [
        "Tu cocina te va a acompañar años.",
        "No diseñes a prueba y error.",
        "Visualizala completa antes de construir.",
        "Escribí COCINA para agendar una reunión.",
    ],
    [
        "Una decisión puede arruinar toda una cocina.",
        "Y la mayoría la toma demasiado rápido.",
        "Te contamos cuál es en la reunión.",
        "Mandá QUIERO y coordinamos.",
    ],
]

TOPICS_CUAN = [
    "distribucion del espacio en la cocina",
    "errores comunes al diseñar una cocina",
    "diseño 3D antes de la obra",
    "islas de cocina: cuando conviene y cuando no",
    "eleccion de materiales para cocina",
    "mesadas y superficies",
    "guardado y almacenamiento en la cocina",
    "errores caros al renovar la cocina",
    "planificar la cocina antes de construir",
    "decisiones que arruinan el diseño de una cocina",
]

# Respuesta cruda de Claude con un emoji a limpiar en la historia 4.
RAW_HILO_CUAN = (
    "El error más caro de una cocina no es la mesada. ||| "
    "Es construir algo que después no funciona. ||| "
    "Por eso diseñamos todo en 3D antes de la obra. ||| "
    "Escribí COCINA 🎉 y coordinamos."
)


def config_cuan(**overrides) -> ClientContentConfig:
    base = {
        "client_id": "cuan-cliente",
        "nombre_negocio": "CUAN",
        "business_description": BUSINESS_DESCRIPTION_CUAN,
        "tone_examples": TONE_EXAMPLES_CUAN,
        "topics": TOPICS_CUAN,
        "prob_link": 0.0,
        # logo_url en None por defecto: los tests no hacen red real.
    }
    base.update(overrides)
    return ClientContentConfig(**base)


def imagen_falsa(w: int = 400, h: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def imagen_candidata(i: int) -> ImagenCandidata:
    return ImagenCandidata(
        drive_file_id=f"drive_{i}",
        drive_file_name=f"img_{i}.jpg",
        image_bytes=imagen_falsa(),
    )


class FakeAnthropicResponse:
    def __init__(self, texto: str = RAW_HILO_CUAN):
        self.content = [SimpleNamespace(text=texto)]


class FakeAnthropicClient:
    def __init__(self, *args, **kwargs):
        self.messages = mock.MagicMock()
        self.messages.create.return_value = FakeAnthropicResponse()

    def crear_para(self, texto: str) -> "FakeAnthropicClient":
        self.messages.create.return_value = FakeAnthropicResponse(texto)
        return self


@pytest.fixture
def mock_servicios(monkeypatch):
    """Mockea Claude y Cloudinary, y setea las env vars que el engine lee."""
    fake_client = FakeAnthropicClient()

    def fake_upload(image_bytes, public_id=None, resource_type=None):
        return {"secure_url": f"https://res.cloudinary.com/storias/{public_id}"}

    fake_upload = mock.MagicMock(side_effect=fake_upload)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "test-cloud")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "test-secret")
    monkeypatch.setattr(content.anthropic, "Anthropic", lambda *a, **k: fake_client)
    monkeypatch.setattr(content.cloudinary.uploader, "upload", fake_upload)
    return fake_client


# ---------------------------------------------------------------------------
# Identidad / migracion
# ---------------------------------------------------------------------------

def test_modelo_de_claude_es_constante_corregida():
    assert CLAUDE_MODEL == "claude-sonnet-5"
    assert CLAUDE_MODEL != "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# generar_hilo
# ---------------------------------------------------------------------------

def test_generar_hilo_devuelve_hilo_con_4_historias_y_4_mas_4_urls(mock_servicios):
    config = config_cuan()
    imagenes = [imagen_candidata(i) for i in range(1, 5)]

    resultado: HiloGenerado = content.generar_hilo(config, imagenes)

    assert isinstance(resultado, HiloGenerado)
    assert len(resultado.historias) == 4
    assert len(resultado.imagenes_originales_url) == 4
    assert len(resultado.imagenes_editadas_url) == 4
    assert all(u.startswith("https://") for u in resultado.imagenes_originales_url)
    assert all(u.startswith("https://") for u in resultado.imagenes_editadas_url)
    assert resultado.drive_file_ids_usados == ["drive_1", "drive_2", "drive_3", "drive_4"]
    # El emoji de la historia 4 se limpio.
    assert "🎉" not in " ".join(resultado.historias)
    # Se subio 4 veces SIN texto y 4 veces editada.
    assert mock_servicios.messages.create.call_count == 1


def test_generar_hilo_con_3_imagenes_levanta_engineerror(mock_servicios):
    config = config_cuan()
    imagenes = [imagen_candidata(i) for i in range(1, 4)]

    with pytest.raises(EngineError, match="exactamente 4"):
        content.generar_hilo(config, imagenes)


def test_generar_hilo_con_0_imagenes_levanta_engineerror(mock_servicios):
    with pytest.raises(EngineError, match="exactamente 4"):
        content.generar_hilo(config_cuan(), [])


def test_error_de_claude_se_envuelve_en_claudegenerationerror(mock_servicios):
    mock_servicios.messages.create.side_effect = RuntimeError("boom de anthropic")

    with pytest.raises(content.ClaudeGenerationError, match="boom de anthropic"):
        content.generar_hilo(config_cuan(), [imagen_candidata(i) for i in range(1, 5)])


# ---------------------------------------------------------------------------
# Prompt: _armar_prompt y eleccion de tema
# ---------------------------------------------------------------------------

def test_prompt_con_weekly_focus_contiene_el_enfoque_obligatorio():
    config = config_cuan(weekly_focus="destacar la venta que cerramos el martes")

    prompt = _armar_prompt(config)

    assert "destacar la venta que cerramos el martes" in prompt
    assert "(obligatorio esta semana)" in prompt
    # No se eligio ningun tema random de la lista.
    assert not any(t in prompt for t in TOPICS_CUAN)


def test_prompt_sin_weekly_focus_usa_un_tema_random_de_topics():
    config = config_cuan()

    prompt = _armar_prompt(config)

    assert any(t in prompt for t in TOPICS_CUAN)


def test_prompt_sin_topics_ni_weekly_focus_usa_fallback_generico():
    config = config_cuan(topics=None)

    prompt = _armar_prompt(config)

    assert TEMA_FALLBACK in prompt
    # El fallback NO es un tema de cocina.
    assert "cocina" not in TEMA_FALLBACK


def test_elegir_tema_prioriza_weekly_focus():
    config = config_cuan(weekly_focus="promocion de la semana")
    assert _elegir_tema(config) == "promocion de la semana"


def test_elegir_tema_sin_weekly_focus_devuelve_topics():
    config = config_cuan()
    assert _elegir_tema(config) in TOPICS_CUAN


def test_elegir_tema_sin_nada_devuelve_fallback():
    assert _elegir_tema(config_cuan(topics=None)) == TEMA_FALLBACK


def test_prompt_generalizado_no_menciona_cocinas_por_defecto():
    prompt = _armar_prompt(config_cuan(weekly_focus="campaña de mes de aniversario"))
    assert "el diferencial de CUAN" in prompt  # por config.nombre_negocio
    assert "arquitectura" not in prompt.lower()


# ---------------------------------------------------------------------------
# editar_historia y generar_texto_de_prueba
# ---------------------------------------------------------------------------

def test_editar_historia_devuelve_asset_de_cloudinary(mock_servicios):
    config = config_cuan()

    imagen_editada = content.editar_historia(config, imagen_falsa(), "Texto nuevo", num_historia=3)

    assert imagen_editada.url.startswith("https://")
    assert "re_edit_3" in imagen_editada.url
    assert "re_edit_3" in imagen_editada.public_id


def test_editar_historia_uses_distinct_cloudinary_public_ids(mock_servicios):
    config = config_cuan()

    first = content.editar_historia(config, imagen_falsa(), "Uno", num_historia=1)
    second = content.editar_historia(config, imagen_falsa(), "Dos", num_historia=1)

    assert first.public_id != second.public_id


def test_editar_historia_usa_el_font_choice_pasado_por_parametro(mock_servicios, monkeypatch):
    # Un override puntual por historia (el empleado elige otra tipografia
    # solo para esta Story desde el editor) debe pisar la del cliente.
    config = config_cuan(font_choice="dm_sans")
    captured = {}
    monkeypatch.setattr(content, "componer_historia",
        lambda *a, **k: captured.update(k) or imagen_falsa())

    content.editar_historia(config, imagen_falsa(), "Texto", num_historia=1, font_choice="poppins")

    assert captured["font_choice"] == "poppins"


def test_editar_historia_sin_override_usa_la_tipografia_del_cliente(mock_servicios, monkeypatch):
    config = config_cuan(font_choice="dm_sans")
    captured = {}
    monkeypatch.setattr(content, "componer_historia",
        lambda *a, **k: captured.update(k) or imagen_falsa())

    content.editar_historia(config, imagen_falsa(), "Texto", num_historia=1)

    assert captured["font_choice"] == "dm_sans"


def test_generar_texto_de_prueba_devuelve_solo_texto(mock_servicios):
    config = config_cuan()

    historias = content.generar_texto_de_prueba(config, imagen_candidata(1))

    assert isinstance(historias, list)
    assert len(historias) == 4
    # No sube nada a Cloudinary.
    assert content.cloudinary.uploader.upload.call_count == 0


# ---------------------------------------------------------------------------
# generar_texto_para_imagen (subida manual: una sola historia, imagen real)
# ---------------------------------------------------------------------------

def test_generar_texto_para_imagen_devuelve_un_solo_texto_limpio(mock_servicios):
    mock_servicios.crear_para("Así se ve tu cocina en 3D antes de la obra 🎉")
    config = config_cuan()

    texto = content.generar_texto_para_imagen(config, imagen_falsa())

    assert isinstance(texto, str)
    assert texto == "Así se ve tu cocina en 3D antes de la obra"
    # No sube nada a Cloudinary: solo genera texto.
    assert content.cloudinary.uploader.upload.call_count == 0
    assert mock_servicios.messages.create.call_count == 1


def test_generar_texto_para_imagen_usa_pocos_tokens_para_una_sola_historia(mock_servicios):
    mock_servicios.crear_para("Una historia corta.")
    content.generar_texto_para_imagen(config_cuan(), imagen_falsa())

    _, kwargs = mock_servicios.messages.create.call_args
    assert kwargs["max_tokens"] == 60


def test_generar_texto_para_imagen_sin_texto_levanta_claudegenerationerror(mock_servicios):
    mock_servicios.crear_para("   ")

    with pytest.raises(content.ClaudeGenerationError, match="no devolvió texto"):
        content.generar_texto_para_imagen(config_cuan(), imagen_falsa())


def test_generar_texto_para_imagen_descarta_todo_despues_del_primer_separador(mock_servicios):
    # Si Claude ignora "una sola historia" y devuelve un hilo de 4 con |||
    # (el formato del prompt semanal), nos quedamos solo con la primera.
    mock_servicios.crear_para(
        "Esa esquina vacía puede ser un rincón de lectura. ||| "
        "Todo depende de cómo pienses el espacio. ||| "
        "Nosotros lo vemos antes de construirlo. ||| "
        "Escribí ESPACIO y te mostramos cómo."
    )
    texto = content.generar_texto_para_imagen(config_cuan(), imagen_falsa())
    assert texto == "Esa esquina vacía puede ser un rincón de lectura."


def test_generar_texto_para_imagen_descarta_lineas_extra(mock_servicios):
    mock_servicios.crear_para("Primera línea.\nSegunda línea que no debería aparecer.")
    texto = content.generar_texto_para_imagen(config_cuan(), imagen_falsa())
    assert texto == "Primera línea."


def test_generar_texto_para_imagen_corta_textos_demasiado_largos(mock_servicios):
    mock_servicios.crear_para("palabra " * 40)
    texto = content.generar_texto_para_imagen(config_cuan(), imagen_falsa())
    assert len(texto) <= 91  # cap + "…"
    assert texto.endswith("…")


def test_generar_texto_para_imagen_envuelve_error_de_claude(mock_servicios):
    mock_servicios.messages.create.side_effect = RuntimeError("boom de anthropic")

    with pytest.raises(content.ClaudeGenerationError, match="boom de anthropic"):
        content.generar_texto_para_imagen(config_cuan(), imagen_falsa())


# ---------------------------------------------------------------------------
# publicar_historia (Meta Graph API)
# ---------------------------------------------------------------------------

def _fake_requests_post(monkeypatch, respuestas):
    def fake_post(url, data=None, **_kw):
        return respuestas.pop(0)

    monkeypatch.setattr(content.requests, "post", fake_post)


def _fake_requests_get_finished(monkeypatch):
    """Default GET mock: container is ready on the first poll — existing
    tests that don't care about polling don't need to think about it."""
    def fake_get(url, params=None, **_kw):
        return SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"status_code": "FINISHED"},
        )

    monkeypatch.setattr(content.requests, "get", fake_get)
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)


def test_publicar_historia_ok_devuelve_resultado_publicacion(monkeypatch):
    class RespOk:
        ok = True

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "POST_456"}

    media_resp = RespOk()
    media_resp.json = lambda: {"id": "MEDIA_123"}
    pub_resp = RespOk()

    _fake_requests_post(monkeypatch, [media_resp, pub_resp])
    _fake_requests_get_finished(monkeypatch)

    resultado = content.publicar_historia(
        image_url="https://res.cloudinary.com/x.jpg",
        instagram_account_id="ig_acct",
        meta_access_token="token",
        agregar_cta=True,
        calendly_link="https://calendly.com/cuan",
    )

    assert isinstance(resultado, ResultadoPublicacion)
    assert resultado.ok is True
    assert resultado.ig_media_id == "POST_456"


def test_publicar_historia_ok_manda_story_cta_solo_con_link(monkeypatch):
    payloads = []

    def fake_post(url, data=None, **_kw):
        payloads.append(data)
        return SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"id": "X"},
        )

    monkeypatch.setattr(content.requests, "post", fake_post)
    _fake_requests_get_finished(monkeypatch)

    content.publicar_historia("url", "acct", "tok", agregar_cta=True, calendly_link="https://cal.com/x")
    assert "story_cta" in payloads[0]

    content.publicar_historia("url", "acct", "tok", agregar_cta=True, calendly_link=None)
    assert "story_cta" not in payloads[2]


def test_publicar_historia_fallo_http_envuelto_en_metapublisheerror(monkeypatch):
    class RespError:
        ok = False

        def raise_for_status(self):
            raise RuntimeError("HTTP 400 desde Meta")

    monkeypatch.setattr(content.requests, "post", lambda *a, **k: RespError())
    _fake_requests_get_finished(monkeypatch)

    with pytest.raises(MetaPublishError, match="HTTP 400"):
        content.publicar_historia("url", "acct", "tok", False, None)


def test_publicar_historia_incluye_el_cuerpo_de_la_respuesta_de_meta_en_el_error(monkeypatch):
    class FakeMetaResponse:
        status_code = 400
        text = '{"error": {"message": "Media type STORIES no soportado para esta cuenta", "code": 100}}'

    class RespError:
        ok = False

        def raise_for_status(self):
            http_err = content.requests.exceptions.HTTPError(
                "400 Client Error: Bad Request for url: https://graph.facebook.com/v21.0/x/media"
            )
            http_err.response = FakeMetaResponse()
            raise http_err

    monkeypatch.setattr(content.requests, "post", lambda *a, **k: RespError())
    _fake_requests_get_finished(monkeypatch)

    with pytest.raises(MetaPublishError, match="Media type STORIES no soportado"):
        content.publicar_historia("url", "acct", "tok", False, None)


def test_publicar_historia_redacta_el_token_antes_de_truncar_el_error_de_meta(monkeypatch):
    token = "SECRET_ACCESS_TOKEN_12345"

    class FakeMetaResponse:
        text = ("x" * 495) + token + "tail"

    class RespError:
        def raise_for_status(self):
            http_err = content.requests.exceptions.HTTPError("400 Client Error")
            http_err.response = FakeMetaResponse()
            raise http_err

    monkeypatch.setattr(content.requests, "post", lambda *a, **k: RespError())
    _fake_requests_get_finished(monkeypatch)

    with pytest.raises(MetaPublishError) as exc_info:
        content.publicar_historia("url", "acct", token, False, None)

    assert token not in str(exc_info.value)
    assert token[:5] not in str(exc_info.value)
    assert "[reda" in str(exc_info.value)


def test_publicar_historia_espera_varios_intentos_antes_de_finished(monkeypatch):
    estados = iter(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    get_calls = []

    def fake_get(url, params=None, **_kw):
        get_calls.append(params)
        return SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"status_code": next(estados)},
        )

    monkeypatch.setattr(content.requests, "get", fake_get)
    sleeps = []
    monkeypatch.setattr(content.time, "sleep", lambda seconds: sleeps.append(seconds))
    _fake_requests_post(monkeypatch, [
        SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"id": "MEDIA_123"},
        ),
        SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"id": "POST_456"},
        ),
    ])

    resultado = content.publicar_historia("url", "acct", "tok", False, None)

    assert resultado.ok is True
    assert len(get_calls) == 3
    assert sleeps == [content.STATUS_POLL_INTERVAL_SECONDS] * 2


def test_publicar_historia_container_en_error_no_publica(monkeypatch):
    monkeypatch.setattr(content.requests, "get", lambda *a, **k: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"status_code": "ERROR"},
    ))
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)
    post_calls = []
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: (
        post_calls.append(url),
        SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"id": "MEDIA_123"},
        ),
    )[1])

    with pytest.raises(MetaPublishError, match="ERROR"):
        content.publicar_historia("url", "acct", "tok", False, None)

    assert len(post_calls) == 1


def test_publicar_historia_container_expirado_no_publica(monkeypatch):
    monkeypatch.setattr(content.requests, "get", lambda *a, **k: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"status_code": "EXPIRED"},
    ))
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"id": "MEDIA_123"},
    ))

    with pytest.raises(MetaPublishError, match="EXPIRED"):
        content.publicar_historia("url", "acct", "tok", False, None)


def test_publicar_historia_consulta_el_estado_del_container_por_su_id(monkeypatch):
    gets = []

    def fake_get(url, params=None, **_kw):
        gets.append(url)
        return SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            json=lambda: {"status_code": "FINISHED"},
        )

    monkeypatch.setattr(content.requests, "get", fake_get)
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"id": "MEDIA_123"},
    ))

    content.publicar_historia("url", "ACCT_999", "tok", False, None)

    assert gets == [f"{content.GRAPH_API_BASE}/MEDIA_123"]
    assert "ACCT_999" not in gets[0]



def test_publicar_historia_timeout_de_polling_tira_metapublisheerror(monkeypatch):
    monkeypatch.setattr(content.requests, "get", lambda *a, **k: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"status_code": "IN_PROGRESS"},
    ))
    sleeps = []
    monkeypatch.setattr(content.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"id": "MEDIA_123"},
    ))

    with pytest.raises(MetaPublishError, match="no terminó de procesarse"):
        content.publicar_historia("url", "acct", "tok", False, None)

    assert len(sleeps) == content.STATUS_POLL_MAX_ATTEMPTS


def test_publicar_historia_redacta_el_token_en_error_de_polling(monkeypatch):
    token = "SECRET_ACCESS_TOKEN_12345"

    def fake_get(url, params=None, **_kw):
        raise RuntimeError(f"fallo consultando {url}?access_token={token}")

    monkeypatch.setattr(content.requests, "get", fake_get)
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"id": "MEDIA_123"},
    ))

    with pytest.raises(MetaPublishError) as exc_info:
        content.publicar_historia("url", "acct", token, False, None)

    assert token not in str(exc_info.value)


def test_publicar_historia_error_de_polling_incluye_cuerpo_de_meta_y_redacta_token(monkeypatch):
    token = "SECRET_ACCESS_TOKEN_12345"

    class FakeHTTPError(Exception):
        def __init__(self):
            super().__init__(
                f"400 Client Error: Bad Request for url: https://graph.facebook.com/v21.0/1/2?fields=status_code&access_token={token}"
            )
            self.response = SimpleNamespace(
                text='{"error":{"message":"Invalid OAuth access token","type":"OAuthException","code":190}}'
            )

    def fake_get(url, params=None, **_kw):
        raise FakeHTTPError()

    monkeypatch.setattr(content.requests, "get", fake_get)
    monkeypatch.setattr(content.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(content.requests, "post", lambda url, data=None, **_kw: SimpleNamespace(
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {"id": "MEDIA_123"},
    ))

    with pytest.raises(MetaPublishError) as exc_info:
        content.publicar_historia("url", "acct", token, False, None)

    message = str(exc_info.value)
    assert "respuesta de Meta" in message
    assert "OAuthException" in message
    assert token not in message
