"""The local 3D shapes solver: segmentation, pair scoring, the refusal margin, evaluation.

The real fixture is TikTok's own 3D challenge recorded on 2026-11-06 (552 x 344; see
``fixtures/shapes_modal.html`` for the source and the operator's licence ruling), with its
two "8"s labelled by hand. The synthetic cases are drawn with OpenCV to pin the refusal and
overlap logic. One real image proves this one image — not an accuracy figure.
"""

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2", reason="the solver's image math needs OpenCV")
numpy = pytest.importorskip("numpy", reason="the solver's image math needs NumPy")

from thoth_control_plane.acquisition.captcha_shapes import (  # noqa: E402
    MAX_MARKS,
    Component,
    _hue_centers,
    marked_image,
    mask_distance,
    objects_in,
    same_shape_pair,
)

FIXTURES = Path(__file__).parent / "fixtures"
#: The real sample's answer, labelled by hand from the image: the large green "8" and the
#: small salmon "8" (boxes in image pixels; the two differ in size and colour).
REAL_EIGHTS = [(110, 152, 55, 87), (204, 230, 36, 54)]
REFUSAL: list = []  # the harness label for a case that must end in points=None


def _inside(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y, w, h = box
    return x <= point[0] <= x + w and y <= point[1] <= y + h


def _star_polygon(cx: int, cy: int, radius: int) -> numpy.ndarray:
    angles = numpy.linspace(0, 2 * numpy.pi, 10, endpoint=False) + numpy.pi / 2
    radii = numpy.where(numpy.arange(10) % 2 == 0, radius, radius * 0.45)
    return numpy.int32(
        [[cx + r * numpy.cos(a), cy + r * numpy.sin(a)] for a, r in zip(angles, radii, strict=True)]
    )


def _card() -> numpy.ndarray:
    return numpy.full((344, 552, 3), 250, numpy.uint8)  # the near-white pastel ground


def _clean_pair() -> tuple[numpy.ndarray, list[tuple[int, int, int, int]]]:
    """Two same-shape stars (the answer, different colours and scales) among three other
    shapes, each its own saturated hue so the hue split keeps every object apart."""
    image = _card()
    cv2.fillPoly(image, [_star_polygon(90, 100, 42)], (0, 0, 255))  # red star
    cv2.fillPoly(image, [_star_polygon(330, 240, 32)], (255, 0, 0))  # blue star, smaller
    cv2.fillPoly(image, [numpy.int32([(420, 60), (500, 60), (460, 130)])], (0, 255, 0))
    cv2.rectangle(image, (200, 40), (280, 76), (0, 255, 255), -1)
    cv2.circle(image, (450, 240), 38, (255, 0, 255), -1)
    return image, [(48, 58, 84, 84), (298, 208, 64, 64)]


def _two_objects() -> numpy.ndarray:
    image = _card()
    cv2.fillPoly(image, [_star_polygon(140, 172, 46)], (0, 0, 255))
    cv2.circle(image, (400, 172), 46, (255, 0, 0), -1)
    return image


def _two_identical_pairs() -> numpy.ndarray:
    """Two pairs of pixel-identical shapes: the margin cannot separate them, so refusing
    is the only safe answer."""
    image = _card()
    cv2.fillPoly(image, [_star_polygon(100, 100, 44)], (0, 0, 255))
    cv2.fillPoly(image, [_star_polygon(330, 100, 44)], (255, 0, 0))
    cv2.circle(image, (180, 250), 44, (0, 255, 0), -1)
    cv2.circle(image, (420, 250), 44, (0, 255, 255), -1)
    return image


def _same_colour_overlap() -> numpy.ndarray:
    """Two overlapping shapes of one colour merge into a single component (the known
    ceiling); the solver must refuse rather than click some other pair."""
    image = _card()
    cv2.fillPoly(image, [numpy.int32([(120, 80), (200, 80), (160, 190)])], (0, 0, 255))
    cv2.fillPoly(image, [numpy.int32([(160, 110), (240, 110), (200, 220)])], (0, 0, 255))
    cv2.circle(image, (420, 100), 40, (0, 255, 0), -1)
    cv2.rectangle(image, (380, 200), (470, 250), (255, 0, 0), -1)
    cv2.rectangle(image, (300, 40), (330, 140), (0, 255, 255), -1)
    return image


def test_hue_centers_counts_the_image_own_colour_groups() -> None:
    values = numpy.concatenate(
        [numpy.full(500, 4.0), numpy.full(900, 63.0), numpy.full(400, 105.0)]
    ).astype(numpy.float32)

    centers = _hue_centers(values)

    assert len(centers) == 3  # not a fixed k: the histogram's three peaks
    assert all(
        min(abs(c - expected), 180 - abs(c - expected)) <= 5
        for c, expected in zip(centers, (4, 63, 105), strict=True)
    )


def test_hue_centers_merges_neighbouring_peaks_of_one_colour() -> None:
    values = numpy.concatenate([numpy.full(800, 60.0), numpy.full(400, 65.0)]).astype(numpy.float32)

    assert len(_hue_centers(values)) == 1


def test_objects_in_finds_every_object_of_the_clean_card() -> None:
    image, _ = _clean_pair()

    objects = objects_in(image)

    assert len(objects) == 5
    assert all(component.area >= 300 for component in objects)
    assert len({component.centroid for component in objects}) == 5


def test_mask_distance_is_zero_for_a_shape_and_its_scale() -> None:
    _, labels = _clean_pair()
    objects = objects_in(_clean_pair()[0])
    stars = [
        component
        for component in objects
        if any(_inside(component.centroid, label) for label in labels)
    ]

    assert len(stars) == 2
    assert mask_distance(*stars) < 0.15  # scale drops out of the normalised masks


def test_mask_distance_takes_the_better_of_plain_and_mirrored() -> None:
    disc = numpy.zeros((40, 40), numpy.uint8)
    cv2.circle(disc, (20, 20), 16, 255, -1)
    symmetric = Component((0, 0, 40, 40), (0.0, 0.0), 800, disc)
    arrow = numpy.zeros((40, 40), numpy.uint8)
    cv2.fillPoly(arrow, [numpy.int32([(0, 8), (34, 20), (0, 32), (10, 20)])], 255)
    asymmetric = Component((0, 0, 40, 40), (0.0, 0.0), 800, arrow)
    mirrored = Component((0, 0, 40, 40), (0.0, 0.0), 800, cv2.flip(arrow, 1))

    assert mask_distance(symmetric, symmetric) == pytest.approx(0.0)
    # A flipped pair matches through the mirrored variant (a padding-anchor pixel or two
    # apart, never exact) — and far closer than any mismatched pair ever scores.
    assert mask_distance(asymmetric, mirrored) < mask_distance(asymmetric, symmetric) / 2


def test_same_shape_pair_answers_the_real_sample() -> None:
    image = cv2.imread(str(FIXTURES / "shapes_sample.jpg"))

    result = same_shape_pair(image)

    assert result.points is not None, "the one real sample must be answered, not refused"
    assert len(result.objects) == 7  # the spike's own count, kept as a regression pin
    assert sorted(_inside(point, label) for point in result.points for label in REAL_EIGHTS) == [
        False,
        False,
        True,
        True,
    ]


def test_same_shape_pair_refuses_below_three_objects() -> None:
    result = same_shape_pair(_two_objects())

    assert result.points is None
    assert len(result.objects) == 2


def test_same_shape_pair_refuses_two_identical_pairs() -> None:
    result = same_shape_pair(_two_identical_pairs())

    assert result.points is None  # the margin cannot separate them: no click


def test_same_shape_overlap_merges_and_then_refuses() -> None:
    result = same_shape_pair(_same_colour_overlap())

    assert len(result.objects) == 4  # the two same-colour triangles are one component
    assert result.points is None


def test_marked_image_draws_numbered_boxes_over_the_candidates() -> None:
    image = _clean_pair()[0]
    objects = objects_in(image)

    marked = marked_image(image, objects)

    assert marked[:4] == b"\x89PNG"
    decoded = cv2.imdecode(numpy.frombuffer(marked, numpy.uint8), cv2.IMREAD_COLOR)
    red = (decoded[:, :, 2] > 200) & (decoded[:, :, 1] < 80) & (decoded[:, :, 0] < 80)
    assert red.sum() > 4 * len(objects)  # the boxes and the numbers are drawn


def test_marked_image_caps_the_marks_at_the_budget() -> None:
    image = _card()
    objects = [
        Component((i * 50, 10, 40, 40), (0.0, 0.0), 900, numpy.full((40, 40), 255, numpy.uint8))
        for i in range(MAX_MARKS + 5)
    ]

    assert marked_image(image, objects) == marked_image(image, objects[:MAX_MARKS])


def _labelled_fixtures() -> list[tuple[str, str, numpy.ndarray, list]]:
    """Every labelled case the offline evaluation runs over: kind, name, image, answer.

    Real cases carry the hand label; synthetic cases carry the constructed one; REFUSAL
    names the cases that must end without a click.
    """
    real = cv2.imread(str(FIXTURES / "shapes_sample.jpg"))
    return [
        ("real", "shapes_sample.jpg (the two 8s)", real, REAL_EIGHTS),
        ("synthetic", "clean pair (two stars)", *_clean_pair()),
        ("synthetic", "two objects only", _two_objects(), REFUSAL),
        ("synthetic", "two identical pairs", _two_identical_pairs(), REFUSAL),
        ("synthetic", "same-colour overlap", _same_colour_overlap(), REFUSAL),
    ]


def test_the_offline_evaluation_answers_every_labelled_fixture(capsys) -> None:
    """The evaluation harness: per image, the pair or the refusal — real and synthetic
    kept apart, and a wrong answer fails the run. One real image is not an accuracy
    figure; this proves each row, never a rate."""
    for kind, name, image, expected in _labelled_fixtures():
        result = same_shape_pair(image)
        if expected is REFUSAL:
            print(f"{kind:<9} {name}: refusal ({len(result.objects)} objects)")
            assert result.points is None, f"{name} must refuse, got {result.points}"
            continue
        assert result.points is not None, f"{name} must be answered"
        matched = sorted(_inside(point, label) for point in result.points for label in expected)
        print(
            f"{kind:<9} {name}: pair {[tuple(round(v, 1) for v in p) for p in result.points]}"
            f" of {len(result.objects)} objects"
        )
        assert matched == [False, False, True, True], f"{name} answered {result.points}"
