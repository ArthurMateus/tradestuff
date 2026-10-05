from typing import Any
from tests.runner.test_reload import pending_close
from tests.runner.scenarios import set_mid_below_stop
from tests.runner.test_mutation_pins import runner_step_no_books

def test_exit(new_world: Any) -> None:
    world, run1, old = pending_close(new_world)
    n = len(world.records())
    set_mid_below_stop(world, run1)
    print("MID", world.hl.mids, [(s.kind, s.trigger_px) for s in run1.broker.stops()])
    for _ in range(6):
        world.clock.advance(300)
        runner_step_no_books(world, run1)
    print("NEW", [(r.kind, r.payload.get("reason")) for r in world.records()[n:]], run1.hub.mids(), run1.hub.mid_time_ms(), world.clock.now)
