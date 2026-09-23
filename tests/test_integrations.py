import email
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'integrations'))
import asistente_email as ae


def fake_response(payload):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class AskBrainTests(unittest.TestCase):
    def test_sends_message_and_returns_decision(self):
        with patch('asistente_email.urlopen', return_value=fake_response({'status': 'completed', 'answer': 'Listo', 'needs_help': False})) as m:
            result = ae.ask_brain('http://127.0.0.1:8765', 'iqk_x', 'Hola, necesito ayuda')
        self.assertEqual(result['answer'], 'Listo')
        req = m.call_args[0][0]
        self.assertEqual(req.get_header('X-iq-api-key'), 'iqk_x')
        self.assertEqual(json.loads(req.data)['message'], 'Hola, necesito ayuda')

    def test_truncates_overly_long_messages(self):
        with patch('asistente_email.urlopen', return_value=fake_response({'status': 'completed', 'answer': 'ok', 'needs_help': False})) as m:
            ae.ask_brain('http://127.0.0.1:8765', 'iqk_x', 'x' * 9000)
        self.assertEqual(len(json.loads(m.call_args[0][0].data)['message']), 6000)

    def test_http_error_is_reported_not_raised(self):
        err = HTTPError('url', 403, 'forbidden', {}, None)
        err.read = lambda: json.dumps({'error': 'Clave de integración inválida.'}).encode()
        with patch('asistente_email.urlopen', side_effect=err):
            result = ae.ask_brain('http://127.0.0.1:8765', 'clave-mala', 'hola')
        self.assertEqual(result['status'], 'error')
        self.assertIn('inválida', result['error'])

    def test_connection_error_is_reported_not_raised(self):
        with patch('asistente_email.urlopen', side_effect=URLError('conexión rechazada')):
            result = ae.ask_brain('http://127.0.0.1:8765', 'iqk_x', 'hola')
        self.assertEqual(result['status'], 'error')
        self.assertIn('No se pudo conectar', result['error'])


class BuildDraftTests(unittest.TestCase):
    def test_resolved_locally_marks_ready(self):
        subject, body = ae.build_draft('Consulta de stock', 'cliente@x.com',
            {'status': 'completed', 'needs_help': False, 'escalated': False, 'answer': 'Tenemos stock disponible.'})
        self.assertTrue(subject.startswith('[BORRADOR LISTO]'))
        self.assertIn('Tenemos stock disponible.', body)

    def test_needs_help_marks_for_review(self):
        subject, body = ae.build_draft('Reclamo', 'cliente@x.com',
            {'status': 'completed', 'needs_help': True, 'answer': 'El motor local todavía no está listo.'})
        self.assertTrue(subject.startswith('[REVISAR]'))
        self.assertIn('redactalo vos', body)

    def test_escalated_answer_is_labeled(self):
        subject, body = ae.build_draft('Precio actual', 'cliente@x.com',
            {'status': 'completed', 'needs_help': False, 'escalated': True, 'answer': 'El precio de hoy es...'})
        self.assertIn('Gemini', body)

    def test_transport_error_never_produces_a_fake_answer(self):
        subject, body = ae.build_draft('Consulta', 'cliente@x.com', {'status': 'error', 'error': 'timeout'})
        self.assertTrue(subject.startswith('[NO SE PUDO PROCESAR]'))
        self.assertIn('timeout', body)


class EmailParsingTests(unittest.TestCase):
    def test_plain_text_extracts_body_from_multipart(self):
        msg = email.message.EmailMessage()
        msg['Subject'] = 'Test'
        msg.set_content('Hola, esto es el cuerpo.')
        msg.add_alternative('<p>Hola, esto es el cuerpo.</p>', subtype='html')
        parsed = email.message_from_bytes(msg.as_bytes())
        self.assertIn('Hola, esto es el cuerpo.', ae.plain_text(parsed))

    def test_decode_handles_plain_ascii_subject(self):
        self.assertEqual(ae.decode('Consulta simple'), 'Consulta simple')

    def test_decode_handles_empty_header(self):
        self.assertEqual(ae.decode(None), '')


if __name__ == '__main__':unittest.main()
