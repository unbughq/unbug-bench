# Practice owner answers

## Manual holds
An explicitly expired manual hold without an order line is not a customer commitment. It may be released using the reservation API. A reservation tied to a live order cannot free that order's stock. The owner wants legitimate expired holds released, rather than blanket refusal of reservation deletion.

## Pending deployments
For P1 (bypass ordinary triggers), the owner blocks deployment: the previous protection depends on those triggers. For P2 (45-second statement timeout), the owner approves.

## Scope
Marketplace orders count against the same stock as Medusa. Their integration holds are not a second customer sale. Backorder exceptions and cancellation behavior follow the contestant promise.
