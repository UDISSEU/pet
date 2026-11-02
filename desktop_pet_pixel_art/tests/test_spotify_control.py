import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import spotify_control
import desktop_pet
from desktop_pet import DesktopPet


class SpotifyCommandTests(unittest.TestCase):
    def test_track_play_commands_extract_title_and_artist(self):
        cases = {
            "toca a música Evidências do Chitãozinho e Xororó no Spotify": {
                "operation": "play_track",
                "track": "Evidências do Chitãozinho e Xororó",
            },
            "bota Evidências do Chitãozinho e Xororó no Spotify": {
                "operation": "play_track",
                "track": "Evidências do Chitãozinho e Xororó",
            },
            "toca música Evidências pra tocar": {
                "operation": "play_track",
                "track": "Evidências",
            },
            "bota uma música": {
                "operation": "play_track",
                "track": "",
            },
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(spotify_control.parse_spotify_command(question), expected)

    def test_open_app_and_playlist_commands_keep_their_existing_intents(self):
        self.assertIsNone(spotify_control.parse_spotify_command("abri Spotify"))
        self.assertEqual(
            spotify_control.parse_spotify_command("toca a playlist Favoritas no Spotify"),
            {"operation": "play", "playlist": "Favoritas"},
        )
        self.assertEqual(
            spotify_control.parse_spotify_command(
                "adiciona Evidências na playlist Favoritas do Spotify"
            ),
            {
                "operation": "add",
                "track": "Evidências",
                "playlist": "Favoritas do Spotify",
            },
        )

    def test_play_track_searches_then_sends_track_to_local_player(self):
        track = {
            "id": "track-id",
            "uri": "spotify:track:track-id",
            "name": "Evidências",
            "artists": [{"name": "Chitãozinho e Xororó"}],
        }
        with mock.patch.object(spotify_control, "_find_track", return_value=track) as find_track, \
             mock.patch.object(
                 spotify_control, "_play_track_locally", return_value="Tocando Evidências."
             ) as play_track:
            result = spotify_control.execute_spotify_action(
                "client-id", "play_track", "", "Evidências Chitãozinho e Xororó"
            )

        find_track.assert_called_once_with("client-id", "Evidências Chitãozinho e Xororó")
        play_track.assert_called_once_with(track)
        self.assertEqual(result, "Tocando Evidências.")

    def test_generic_music_request_prompts_for_a_track_name(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._spotify_action_active = False
        pet.show_bubble = mock.Mock()
        request = spotify_control.parse_spotify_command("bota uma música")

        pet._start_spotify_request("bota uma música", request)

        self.assertIn("Qual música você quer ouvir?", pet.show_bubble.call_args.args[0])
        self.assertIsNotNone(pet._spotify_pending_track_at)

    def test_followup_track_name_is_attached_to_the_pending_music_request(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.ai_request_active = False
        pet._spotify_pending_track_at = time.monotonic()
        pet._ask_question = mock.Mock(return_value="Evidências do Chitãozinho e Xororó")
        pet._record_interaction = mock.Mock()
        pet._start_spotify_request = mock.Mock()

        pet.ask_menu()

        pet._start_spotify_request.assert_called_once_with(
            "Evidências do Chitãozinho e Xororó",
            {
                "operation": "play_track",
                "track": "Evidências do Chitãozinho e Xororó",
            },
        )
        self.assertIsNone(pet._spotify_pending_track_at)

    def test_named_track_request_starts_the_spotify_worker_when_connected(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._spotify_action_active = False
        pet.settings = {"spotify_client_id": "client-id"}
        pet.show_bubble = mock.Mock()
        question = "toca Evidências no Spotify"
        request = spotify_control.parse_spotify_command(question)
        with mock.patch.object(desktop_pet, "spotify_token_connected", return_value=True), \
             mock.patch.object(desktop_pet.threading, "Thread") as thread:
            pet._start_spotify_request(question, request)

        self.assertTrue(pet._spotify_action_active)
        self.assertEqual(thread.call_args.kwargs["target"], pet._spotify_action_worker)
        self.assertEqual(
            thread.call_args.kwargs["args"], (question, request, "client-id")
        )

    def test_track_uri_is_opened_and_played_through_mpris(self):
        track = {
            "id": "track-id",
            "uri": "spotify:track:track-id",
            "name": "Evidências",
            "artists": [{"name": "Chitãozinho e Xororó"}],
        }
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(
            spotify_control.shutil,
            "which",
            side_effect=lambda name: {
                "spotify": "/usr/bin/spotify",
                "gdbus": "/usr/bin/gdbus",
            }.get(name),
        ), mock.patch.object(spotify_control.subprocess, "Popen", return_value=process), \
             mock.patch.object(spotify_control.subprocess, "run") as run, \
             mock.patch.object(spotify_control.time, "sleep"):
            result = spotify_control._play_track_locally(track)

        self.assertIn("Evidências", result)
        self.assertIn("Chitãozinho e Xororó", result)
        self.assertTrue(any(
            "spotify:track:track-id" in argument
            for argument in run.call_args_list[0].args[0]
        ))
        self.assertIn("org.mpris.MediaPlayer2.Player.Play", run.call_args_list[1].args[0])
