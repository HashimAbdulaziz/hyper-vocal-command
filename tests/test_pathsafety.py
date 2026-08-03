from hypr_vocal_command.resolvers.pathsafety import resolve_within


def test_path_within_allowed_root_resolves(tmp_path):
    allowed = [tmp_path]
    target = tmp_path / "notes" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hi")

    resolved = resolve_within(target, allowed)

    assert resolved == target.resolve()


def test_path_traversal_outside_allowed_root_is_rejected(tmp_path):
    allowed_root = tmp_path / "safe"
    allowed_root.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("secret")

    traversal_attempt = allowed_root / ".." / "outside" / "secret.txt"

    resolved = resolve_within(traversal_attempt, [allowed_root])

    assert resolved is None


def test_root_itself_resolves(tmp_path):
    assert resolve_within(tmp_path, [tmp_path]) == tmp_path.resolve()
