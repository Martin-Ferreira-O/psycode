import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase

from backend.apps.accounts.models import Role
from backend.apps.capture.authentication import (
    AgentIdentity,
    authenticate_agent_header,
)
from backend.apps.capture.models import (
    AcceptedSequence,
    AgentConnectivityEvent,
    AgentRegistration,
    AgentStatus,
    CaptureSession,
    RuntimeLease,
    ServerConnectivityOutage,
)
from backend.apps.capture.server_connectivity import (
    register_server_disconnect,
    register_server_reconnect,
)

User = get_user_model()


class AgentRegistrationAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_scrum96",
            email="admin96@clinica.cl",
            password="Password-Segura-123",
            role=Role.ADMIN,
        )

        self.supervisor = User.objects.create_user(
            username="supervisor_scrum96",
            email="supervisor96@clinica.cl",
            password="Password-Segura-123",
            role=Role.SUPERVISOR,
        )

        self.url = "/api/v1/pcs"

    def record_pc_status(self, *, box, seen_at, diagnostics):
        agent = AgentRegistration.objects.get(box=box)
        agent.last_seen_at, agent.diagnostics = seen_at, diagnostics
        agent.save(update_fields=["last_seen_at", "diagnostics"])
        return AgentStatus.objects.create(box=box, seen_at=seen_at, diagnostics=diagnostics)

    def test_admin_puede_crear_pc_y_recibe_api_key(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.url,
            {
                "name": "PC Box 3",
                "box": "box-3",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        data = response.data["data"]

        self.assertEqual(data["name"], "PC Box 3")
        self.assertEqual(data["box"], "box-3")
        self.assertTrue(data["active"])
        self.assertIn("api_key", data)
        agent = AgentRegistration.objects.get(
            agent_id=data["agent_id"]
        )


        self.assertNotEqual(
            agent.token_sha256,
            data["api_key"],
        )

        self.assertEqual(
            len(agent.token_sha256),
            64,
        )
    def test_api_key_no_se_muestra_al_listar(self):
        self.client.force_authenticate(user=self.admin)
        create_response = self.client.post(
            self.url,
            {
                "name": "PC Box 4",
                "box": "box-4",
            },
            format="json",
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )
        api_key = create_response.data["data"]["api_key"]
        response = self.client.get(self.url)
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        agents = response.data["data"]
        self.assertEqual(len(agents), 1)
        listed_agent = agents[0]
        self.assertNotIn("api_key", listed_agent)
        self.assertNotIn("token_sha256", listed_agent)
        self.assertNotIn(
            api_key,
            str(response.data),
        )

    def test_identificador_es_independiente_del_nombre(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.url,
            {
                "name": "PC Recepción Box 5",
                "box": "box-5",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        agent_id = response.data["data"]["agent_id"]

        agent = AgentRegistration.objects.get(
            agent_id=agent_id
        )

        agent.name = "PC Renombrado"
        agent.save(update_fields=["name", "updated_at"])

        self.assertEqual(
            str(agent.agent_id),
            agent_id,
        )

    def test_supervisor_no_puede_listar_ni_crear(self):
        self.client.force_authenticate(
            user=self.supervisor
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        response = self.client.post(
            self.url,
            {
                "name": "PC No Permitido",
                "box": "box-6",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertEqual(
            AgentRegistration.objects.count(),
            0,
        )

    def test_usuario_no_autenticado_es_rechazado(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_rechaza_identificador_box_invalido(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.url,
            {
                "name": "PC Box inválido",
                "box": "box-0",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            AgentRegistration.objects.count(),
            0,
        )

    def test_revocacion_conserva_el_pc_e_invalida_su_credencial(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Seguridad Box 3",
                "box": "box-3",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]
        api_key = create_response.data["data"]["api_key"]

        header = f"Agent {api_key}".encode("ascii")

        identity = authenticate_agent_header(header)

        self.assertEqual(
            identity.agent_id,
            agent_id,
        )

        self.assertEqual(
            identity.box,
            "box-3",
        )
        response = self.client.post(
            f"/api/v1/pcs/{agent_id}/revocar"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        agent = AgentRegistration.objects.get(agent_id=agent_id)
        self.assertFalse(agent.is_active)
        self.assertIsNotNone(agent.revoked_at)

        with self.assertRaises(AuthenticationFailed):
            authenticate_agent_header(header)

    def test_renovacion_conserva_el_pc_y_reemplaza_su_credencial(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Seguridad Box 4",
                "box": "box-4",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]
        old_api_key = create_response.data["data"]["api_key"]
        agent = AgentRegistration.objects.get(agent_id=agent_id)
        old_hash = agent.token_sha256

        old_header = f"Agent {old_api_key}".encode("ascii")
        old_identity = authenticate_agent_header(
            old_header
        )

        self.assertEqual(
            old_identity.agent_id,
            agent_id,
        )
        response = self.client.post(
            f"/api/v1/pcs/{agent_id}/renovar"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(response.data["data"]["agent_id"], agent_id)
        new_api_key = response.data["data"]["api_key"]

        self.assertNotEqual(
            old_api_key,
            new_api_key,
        )
        agent.refresh_from_db()
        self.assertNotEqual(agent.token_sha256, old_hash)
        self.assertTrue(agent.is_active)
        self.assertIsNone(agent.revoked_at)
        with self.assertRaises(AuthenticationFailed):
            authenticate_agent_header(old_header)
        new_header = f"Agent {new_api_key}".encode(
            "ascii"
        )

        new_identity = authenticate_agent_header(
            new_header
        )

        self.assertEqual(new_identity.registry_id, str(agent.pk))
        self.assertEqual(
            new_identity.agent_id,
            agent_id,
        )

        self.assertEqual(
            new_identity.box,
            "box-4",
        )

    def test_listado_muestra_estado_operativo_del_pc(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Estado Box 3",
                "box": "box-3",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.record_pc_status(
            box="box-3",
            seen_at=timezone.now(),
            diagnostics={
                "agent_version": "1.0.0",
                "capturing": True,
                "pending": 3,
                "free_bytes": 50000000000,
                "obs": "ready",
                "operational_code": "",
                "smile_last_sync": None,
            },
        )

        lease = RuntimeLease.objects.create(
            name="control:box-3",
            owner=uuid.uuid4(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        AgentRegistration.objects.filter(box="box-3").update(control_owner=lease.owner)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        pc = response.data["data"][0]

        self.assertEqual(
            pc["version"],
            "1.0.0",
        )

        self.assertEqual(
            pc["connection"],
            "online",
        )

        self.assertTrue(
            pc["capturing"]
        )

        self.assertEqual(
            pc["pending"],
            3,
        )

        self.assertEqual(
            pc["free_bytes"],
            50000000000,
        )

        self.assertEqual(
            pc["obs"],
            "ready",
        )

        self.assertIn(
            "last_seen_at",
            pc,
        )


    def test_listado_muestra_ultimo_audio_aceptado(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Audio Box 4",
                "box": "box-4",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        now = timezone.now()

        session = CaptureSession.objects.create(
            box="box-4",
            state="activa",
            origin="agenda",
            scheduled_start=now - timedelta(hours=1),
            scheduled_end=now + timedelta(hours=1),
            authorized_at=now - timedelta(hours=1),
            actual_start=now - timedelta(minutes=30),
            last_seen_at=now,
        )

        sequence = AcceptedSequence.objects.create(
            agent_id=create_response.data["data"]["agent_id"],
            session=session,
            number=1,
            captured_at=now - timedelta(seconds=10),
            accepted_at=now - timedelta(seconds=5),
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        pc = response.data["data"][0]

        self.assertIsNotNone(
            pc["last_audio"],
        )

        self.assertEqual(
            pc["last_audio"]["captured_at"],
            sequence.captured_at,
        )

        self.assertEqual(
            pc["last_audio"]["accepted_at"],
            sequence.accepted_at,
        )

    def test_listado_separa_captura_recepcion_y_procesamiento(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Pipeline Box 5",
                "box": "box-5",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        now = timezone.now()

        session = CaptureSession.objects.create(
            box="box-5",
            state="activa",
            origin="agenda",
            scheduled_start=now - timedelta(minutes=10),
            scheduled_end=now + timedelta(hours=1),
            authorized_at=now - timedelta(minutes=10),
            actual_start=now - timedelta(minutes=5),
            last_seen_at=now,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        pc = response.data["data"][0]

        self.assertEqual(
            pc["capture_status"],
            "active",
        )

        self.assertEqual(
            pc["reception_status"],
            "pending",
        )

        self.assertEqual(
            pc["processing_status"],
            "pending",
        )

        self.assertIsNotNone(
            pc["pipeline"],
        )

        self.assertEqual(
            pc["pipeline"]["session_id"],
            str(session.session_id),
        )

        self.assertEqual(
            pc["pipeline"]["capture"],
            "active",
        )

        self.assertEqual(
            pc["pipeline"]["reception"],
            "pending",
        )

        self.assertEqual(
            pc["pipeline"]["processing"],
            "pending",
        )

    def test_historial_muestra_caida_reportada_por_agente(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Historial Box 3",
                "box": "box-3",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        now = timezone.now()
        outage_id = uuid.uuid4()

        AgentConnectivityEvent.objects.create(
            event_id=uuid.uuid4(),
            agent_id=agent_id,
            box="box-3",
            session_id=None,
            kind="wss.disconnected",
            occurred_at=now - timedelta(minutes=10),
            received_at=now - timedelta(minutes=10),
            outage_id=outage_id,
            duration_ms=None,
            cause="TIMEOUT",
        )

        AgentConnectivityEvent.objects.create(
            event_id=uuid.uuid4(),
            agent_id=agent_id,
            box="box-3",
            session_id=None,
            kind="wss.reconnected",
            occurred_at=now - timedelta(minutes=5),
            received_at=now - timedelta(minutes=5),
            outage_id=outage_id,
            duration_ms=300000,
            cause="",
        )
        RuntimeLease.objects.create(
            name="control:box-3",
            owner=uuid.uuid4(),
            expires_at=now + timedelta(minutes=5),
        )

        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = response.data["data"]["results"]

        self.assertEqual(
            len(results),
            1,
        )

        event = results[0]

        self.assertEqual(
            event["source"],
            "agent_reported",
        )

        self.assertEqual(
            event["channel"],
            "wss",
        )

        self.assertEqual(
            event["cause"],
            "TIMEOUT",
        )

        self.assertEqual(
            event["duration_ms"],
            300000,
        )

        self.assertFalse(
            event["active"]
        )

        self.assertEqual(
            event["start_time_quality"],
            "reported",
        )

        self.assertEqual(
            event["recovery_time_quality"],
            "reported",
        )

    def test_historial_muestra_desconexion_inferida_por_servidor(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Offline Box 4",
                "box": "box-4",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        last_seen = timezone.now() - timedelta(minutes=8)

        self.record_pc_status(
            box="box-4",
            seen_at=last_seen,
            diagnostics={
                "agent_version": "1.0.0",
                "capturing": False,
            },
        )

        identity = AgentIdentity(
            agent_id=agent_id,
            box="box-4",
            managed=True,
        )
        outage = register_server_disconnect(
            identity,
            cause="UNKNOWN",
        )

        self.assertIsNotNone(
            outage,
        )

        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = response.data["data"]["results"]

        self.assertEqual(
            len(results),
            1,
        )

        event = results[0]

        self.assertEqual(
            event["source"],
            "server_inferred",
        )

        self.assertEqual(
            event["channel"],
            "wss",
        )

        self.assertTrue(
            event["active"],
        )

        self.assertEqual(
            event["cause"],
            "UNKNOWN",
        )

        self.assertEqual(
            event["start_time_quality"],
            "estimated",
        )

        self.assertEqual(
            event["recovery_time_quality"],
            "unknown",
        )

        self.assertIsNone(
            event["recovered_at"],
        )

        self.assertIsNotNone(
            event["duration_ms"],
        )

        self.assertEqual(
            event["outage_id"],
            str(outage.outage_id),
        )

    def test_supervisor_no_puede_consultar_historial(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Protegido Box 5",
                "box": "box-5",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        self.client.force_authenticate(
            user=self.supervisor
        )

        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_historial_permite_filtrar_por_fecha(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Filtro Box 6",
                "box": "box-6",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        now = timezone.now()
        AgentConnectivityEvent.objects.create(
            event_id=uuid.uuid4(),
            agent_id=agent_id,
            box="box-6",
            session_id=None,
            kind="wss.disconnected",
            occurred_at=now - timedelta(days=10),
            received_at=now - timedelta(days=10),
            outage_id=uuid.uuid4(),
            duration_ms=None,
            cause="OLD_EVENT",
        )
        recent_outage_id = uuid.uuid4()

        AgentConnectivityEvent.objects.create(
            event_id=uuid.uuid4(),
            agent_id=agent_id,
            box="box-6",
            session_id=None,
            kind="wss.disconnected",
            occurred_at=now - timedelta(days=1),
            received_at=now - timedelta(days=1),
            outage_id=recent_outage_id,
            duration_ms=None,
            cause="RECENT_EVENT",
        )
        RuntimeLease.objects.create(
            name="control:box-6",
            owner=uuid.uuid4(),
            expires_at=now + timedelta(minutes=5),
        )

        date_from = (
            now - timedelta(days=2)
        ).date().isoformat()

        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
            f"?desde={date_from}"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = response.data["data"]["results"]

        self.assertEqual(
            len(results),
            1,
        )

        self.assertEqual(
            results[0]["cause"],
            "RECENT_EVENT",
        )


    def test_historial_es_paginado(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Paginación Box 7",
                "box": "box-7",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        now = timezone.now()
        for index in range(5):
            AgentConnectivityEvent.objects.create(
                event_id=uuid.uuid4(),
                agent_id=agent_id,
                box="box-7",
                session_id=None,
                kind="wss.disconnected",
                occurred_at=now - timedelta(
                    minutes=index + 1
                ),
                received_at=now - timedelta(
                    minutes=index + 1
                ),
                outage_id=uuid.uuid4(),
                duration_ms=None,
                cause=f"EVENT_{index}",
            )
        RuntimeLease.objects.create(
            name="control:box-7",
            owner=uuid.uuid4(),
            expires_at=now + timedelta(minutes=5),
        )

        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
            "?page=1&page_size=2"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        data = response.data["data"]

        self.assertEqual(
            len(data["results"]),
            2,
        )

        self.assertEqual(
            data["pagination"]["page"],
            1,
        )

        self.assertEqual(
            data["pagination"]["page_size"],
            2,
        )

        self.assertEqual(
            data["pagination"]["total"],
            5,
        )

        self.assertEqual(
            data["pagination"]["total_pages"],
            3,
        )
    def test_servidor_persiste_desconexion_inferida_sin_duplicarla(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Caída Box 3",
                "box": "box-3",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        last_seen = timezone.now() - timedelta(minutes=4)

        self.record_pc_status(
            box="box-3",
            seen_at=last_seen,
            diagnostics={
                "agent_version": "1.0.0",
            },
        )

        identity = AgentIdentity(
            agent_id=agent_id,
            box="box-3",
            managed=True,
        )

        first = register_server_disconnect(
            identity,
            cause="CONNECTION_LOST",
        )

        second = register_server_disconnect(
            identity,
            cause="CONNECTION_LOST",
        )

        self.assertIsNotNone(first)
        self.assertEqual(
            first.outage_id,
            second.outage_id,
        )

        self.assertEqual(
            ServerConnectivityOutage.objects.count(),
            1,
        )

        outage = ServerConnectivityOutage.objects.get()

        self.assertEqual(
            outage.agent_id,
            first.agent_id,
        )

        self.assertEqual(
            outage.box,
            "box-3",
        )

        self.assertEqual(
            outage.started_at,
            last_seen,
        )

        self.assertEqual(
            outage.start_time_quality,
            "estimated",
        )

        self.assertIsNone(
            outage.recovered_at,
        )

        self.assertEqual(
            outage.cause,
            "CONNECTION_LOST",
        )


    def test_reconexion_cierra_caida_inferida_existente(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Recuperación Box 4",
                "box": "box-4",
            },
            format="json",
        )

        agent_id = create_response.data["data"]["agent_id"]

        self.record_pc_status(
            box="box-4",
            seen_at=timezone.now() - timedelta(minutes=5),
            diagnostics={},
        )

        identity = AgentIdentity(
            agent_id=agent_id,
            box="box-4",
            managed=True,
        )

        outage = register_server_disconnect(
            identity,
        )

        original_outage_id = outage.outage_id

        recovered = register_server_reconnect(
            identity,
        )

        self.assertIsNotNone(
            recovered,
        )

        self.assertEqual(
            recovered.outage_id,
            original_outage_id,
        )

        recovered.refresh_from_db()

        self.assertIsNotNone(
            recovered.recovered_at,
        )

        self.assertIsNotNone(
            recovered.recovery_detected_at,
        )

        self.assertEqual(
            recovered.recovery_time_quality,
            "estimated",
        )

        self.assertFalse(
            recovered.is_active,
        )
        self.assertEqual(
            ServerConnectivityOutage.objects.count(),
            1,
        )

    def test_historial_conserva_caida_inferida_despues_de_reconexion(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Historial Persistente Box 3",
                "box": "box-3",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        agent_id = create_response.data["data"]["agent_id"]

        last_seen = timezone.now() - timedelta(minutes=6)

        self.record_pc_status(
            box="box-3",
            seen_at=last_seen,
            diagnostics={
                "agent_version": "1.0.0",
            },
        )

        identity = AgentIdentity(
            agent_id=agent_id,
            box="box-3",
            managed=True,
        )
        outage = register_server_disconnect(
            identity,
            cause="CONNECTION_LOST",
        )

        self.assertIsNotNone(outage)
        recovered = register_server_reconnect(
            identity,
        )

        self.assertIsNotNone(recovered)
        self.assertEqual(
            ServerConnectivityOutage.objects.count(),
            1,
        )

        recovered.refresh_from_db()

        self.assertFalse(
            recovered.is_active,
        )

        self.assertIsNotNone(
            recovered.recovered_at,
        )
        response = self.client.get(
            f"/api/v1/pcs/{agent_id}/historial"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = response.data["data"]["results"]

        self.assertEqual(
            len(results),
            1,
        )

        event = results[0]

        self.assertEqual(
            event["source"],
            "server_inferred",
        )

        self.assertEqual(
            event["outage_id"],
            str(outage.outage_id),
        )

        self.assertEqual(
            event["cause"],
            "CONNECTION_LOST",
        )

        self.assertFalse(
            event["active"],
        )

        self.assertEqual(
            event["start_time_quality"],
            "estimated",
        )

        self.assertEqual(
            event["recovery_time_quality"],
            "estimated",
        )

        self.assertIsNotNone(
            event["started_at"],
        )

        self.assertIsNotNone(
            event["recovered_at"],
        )

        self.assertIsNotNone(
            event["duration_ms"],
        )

    def test_listado_muestra_autonomia_y_aviso_de_almacenamiento(self):
        self.client.force_authenticate(user=self.admin)

        create_response = self.client.post(
            self.url,
            {
                "name": "PC Storage Box 3",
                "box": "box-3",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.record_pc_status(
            box="box-3",
            seen_at=timezone.now(),
            diagnostics={
                "agent_version": "1.0.0",
                "free_bytes": 20 * 1024**3,
                "remaining_seconds": 7200,
                "operational_code": "STORAGE_WARNING",
            },
        )

        response = self.client.get(
            self.url,
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        pc = response.data["data"][0]

        self.assertEqual(
            pc["remaining_seconds"],
            7200,
        )

        self.assertEqual(
            pc["free_bytes"],
            20 * 1024**3,
        )

        self.assertEqual(
            pc["operational_code"],
            "STORAGE_WARNING",
        )

        self.assertTrue(
            pc["storage_warning"]["active"],
        )

        self.assertEqual(
            pc["storage_warning"]["level"],
            "warning",
        )

        self.assertEqual(
            pc["storage_warning"]["code"],
            "STORAGE_WARNING",
        )
