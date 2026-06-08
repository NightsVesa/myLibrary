from pathlib import Path

from PIL import Image

from ui.main_window import IDLE_ACTION_REST_S, PET_FRAME_MS, _sprite_frame_index_for_time, _sprite_paths_for_state


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
PET_BG = (255, 0, 255)


def test_sprite_sequence_preferred_over_single_frame(tmp_path):
    fallback = tmp_path / "pet_idle.png"
    fallback.touch()
    first = tmp_path / "pet_idle_00.png"
    second = tmp_path / "pet_idle_01.png"
    first.touch()
    second.touch()

    assert _sprite_paths_for_state(tmp_path, "idle") == [first, second]


def test_sprite_sequence_sorted_by_numeric_suffix(tmp_path):
    paths = [
        tmp_path / "pet_idle_10.png",
        tmp_path / "pet_idle_02.png",
        tmp_path / "pet_idle_00.png",
        tmp_path / "pet_idle_01.png",
    ]
    for path in paths:
        path.touch()
    (tmp_path / "pet_idle_note.png").touch()

    assert _sprite_paths_for_state(tmp_path, "idle") == [
        tmp_path / "pet_idle_00.png",
        tmp_path / "pet_idle_01.png",
        tmp_path / "pet_idle_02.png",
        tmp_path / "pet_idle_10.png",
    ]


def test_sprite_falls_back_to_single_frame(tmp_path):
    fallback = tmp_path / "pet_sleep.png"
    fallback.touch()

    assert _sprite_paths_for_state(tmp_path, "sleep") == [fallback]


def test_idle_sprite_stays_still_between_occasional_actions():
    assert _sprite_frame_index_for_time("idle", 0.0, 8) == 0
    assert _sprite_frame_index_for_time("idle", IDLE_ACTION_REST_S - 0.1, 8) == 0


def test_idle_sprite_plays_one_slow_action_after_rest():
    frame_s = PET_FRAME_MS["idle"] / 1000

    assert _sprite_frame_index_for_time("idle", IDLE_ACTION_REST_S + frame_s * 1.1, 8) == 1
    assert _sprite_frame_index_for_time("idle", IDLE_ACTION_REST_S + frame_s * 3.1, 8) == 3


def test_non_idle_sprite_frames_loop_by_state_timing():
    frame_s = PET_FRAME_MS["happy"] / 1000

    assert _sprite_frame_index_for_time("happy", 0.0, 8) == 0
    assert _sprite_frame_index_for_time("happy", frame_s * 2.1, 8) == 2
    assert _sprite_frame_index_for_time("happy", frame_s * 8.1, 8) == 0


def test_pet_animation_assets_keep_chroma_key_contract():
    paths = sorted(ASSETS_DIR.glob("pet_*_[0-9][0-9].png"))
    assert paths

    for path in paths:
        image = Image.open(path).convert("RGB")
        assert image.size == (301, 180), path.name

        pixels = image.load()
        corners = [
            pixels[0, 0],
            pixels[300, 0],
            pixels[0, 179],
            pixels[300, 179],
        ]
        assert corners == [PET_BG, PET_BG, PET_BG, PET_BG], path.name

        edge_pixels = []
        edge_pixels.extend(pixels[x, 0] for x in range(301))
        edge_pixels.extend(pixels[x, 179] for x in range(301))
        edge_pixels.extend(pixels[0, y] for y in range(180))
        edge_pixels.extend(pixels[300, y] for y in range(180))
        assert all(pixel == PET_BG for pixel in edge_pixels), path.name

        non_bg_pixels = sum(
            1
            for y in range(180)
            for x in range(301)
            if pixels[x, y] != PET_BG
        )
        assert non_bg_pixels > 5_000, path.name
