from sikumon.database.migrations import MigrationStep, plan_migrations


def test_future_migrations_are_planned_as_an_explicit_sequential_chain() -> None:
    def no_op(engine: object) -> None:
        pass

    future_registry = (
        MigrationStep(0, 1, no_op),
        MigrationStep(1, 2, no_op),
        MigrationStep(2, 3, no_op),
    )

    planned = plan_migrations(1, 3, future_registry)

    assert [(step.from_version, step.to_version) for step in planned] == [(1, 2), (2, 3)]


def test_migration_planning_rejects_a_gap() -> None:
    def no_op(engine: object) -> None:
        pass

    future_registry = (MigrationStep(0, 1, no_op), MigrationStep(2, 3, no_op))

    try:
        plan_migrations(1, 3, future_registry)
    except RuntimeError as error:
        assert "1 to 2" in str(error)
    else:
        raise AssertionError("A migration gap must fail explicitly")
