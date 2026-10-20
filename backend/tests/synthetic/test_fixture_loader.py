from synthetic.fixture_loader import generate_fixtures, load_fixtures
from synthetic.omerlo_fixtures import OmerloFixtureGenerator, Sizes, write_fixtures

SMALL = Sizes(organizations=20, people=30, events=4, projects=3, journalists=4)


def test_loaded_fixtures_match_what_was_written(tmp_path):
    generated = OmerloFixtureGenerator(3, SMALL).generate()
    write_fixtures(generated, tmp_path, 3)

    loaded = load_fixtures(tmp_path)

    assert [t.tenant for t in loaded] == [t.tenant for t in generated]
    for written, read in zip(generated, loaded, strict=True):
        assert read.resources == written.resources
        assert read.metadata == written.metadata


def test_ground_truth_is_never_loaded(tmp_path):
    write_fixtures(OmerloFixtureGenerator(3, SMALL).generate(), tmp_path, 3)

    assert all(t.ground_truth == {} for t in load_fixtures(tmp_path))
    assert all(t.ground_truth == {} for t in generate_fixtures(3, SMALL))
