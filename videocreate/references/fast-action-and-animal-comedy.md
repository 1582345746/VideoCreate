# Fast action and animal comedy

Use these workflows for a brisk physical exchange or a pet hero with a reversal. Do not apply rapid cutting to portraits, emotional dialogue or landscape takes unless requested.

## What the historical pilots exposed

Keeping six complete ten-second takes made the API duration dictate the edit. Independent POV takes changed viewpoint, bridge distance, light and road geography. Several shots announced a battle without showing the decisive result. A stronger camera prompt or another candidate did not reliably fix those failures. Plan a smaller event that the audience can recognize and verify from the actual output.

Separate three choices: **subject speed** (one brisk action), **camera movement** (often fixed to keep contact readable), and **retained duration** (the part worth watching). Fast subject motion does not require a shaking camera. A 10-second maximum is not a minimum edit length. Do not spread one quick strike across a multi-second wind-up/contact merely to fill a request. Do not speed up malformed contact to make it look forceful.

## Editable starting plans

```powershell
python scripts/videocreate.py plan init projects/action-test --profile action-montage --seconds 15
python scripts/videocreate.py plan init projects/cat-test --profile animal-comedy --seconds 18 --aspect-ratio 9:16
python scripts/videocreate.py plan validate projects/cat-test
python scripts/videocreate.py plan audit projects/cat-test --output projects/cat-test/coverage-audit.json
python scripts/videocreate.py plan preview projects/cat-test
```

`action-montage` contains a performer striking a training bag once. `animal-comedy` contains an orange cat treating a robot vacuum as an enemy, then riding it. They are worked examples for adaptation, not generated films. Author all story, assets, geography and actions when changing the premise; a new title alone does not change the example. Source takes are 4–10 seconds, with source handles and shorter provisional windows at rate 1. Actual timing must be selected after generation. Check the chosen binding's supported duration steps before requesting anything.

The coverage sequence is spatial setup → attention → limb/prop preparation → one readable contact → visible result → reaction → payoff. A 15-second piece can retain roughly 1–2.5 seconds per setup/detail/action and allow a longer final reveal. This is an example rhythm, not a mandatory shot count. At least one medium view should connect subject and target; disconnected eye/paw/weapon close-ups can be just as confusing as a busy wide shot.

When the reference's appeal is a cat fighting black-clad humans, retain the humans and the actual combat: an incoming threat, the cat evading or countering it, and a visible opponent response. Lock these core elements in the project intent and compare the proposed shots against them before generation. Narrow choreography to one active attacker per exchange if useful while preserving the encounter and its intensity; distant opponents can establish the surrounding threat. A wooden target or feather-toy reversal belongs to a requested practice/comedy premise and does not satisfy an enemy-fight request.

Preserve feline paws, number of limbs, fur markings, hat fit and scale. A bipedal fantasy hero needs an explicit stable anatomy design rather than alternating between animal and human bodies. Multiple colliding bodies, blades and spinning limbs are a harder experiment; test an actual attack/evasion and counter/recoil before expanding. Use independently composed opening frames with identity/wardrobe detail references; avoid feeding one scenic master into every shot.

## Pilot and editing decisions

Test the decisive contact/result pair first within current authorization. For requested combat, include the actual opponent in this pilot and check both the incoming threat and its answered consequence; a solo pose or prop demonstration cannot validate it. Inspect whether contact is visible, the result happens for the same reason, and the subject stays recognizable. A reaction shot cannot repair an unreadable core action. If the pair fails, simplify or redesign the exchange while keeping the requested participants and event before generating a whole minute. Reference images help appearance and initial layout; they do not certify choreography, collisions or temporal consistency. Handoff helps adjacent physical continuation; result/reaction coverage can also use intentional edits with matched direction.

Independent coverage can run concurrently after the pilot. Continuation from an observed ending needs a saved handoff and dependency. Review every output individually; high concurrency does not raise acceptance quality.

Select actual source in/out around a complete visual unit. A brief hold before impact and an observable effect after it help readability. Keep clear spatial direction across cuts. Distinguish a deliberate ellipsis (cat is now seated on a vacuum) from a missing decisive action (a truck never visibly stops). Do not append an unexplained result to make an incomplete source appear successful.

Use continuous ambience, a precisely placed contact sound, cloth/foot sounds, a short gap and a reveal sound when appropriate. Place independent effects in timeline time after the edit is chosen. These are sound design plans until real assets are attached and listened to; do not infer good sound from an audio stream existing. Dialogue is optional; a visual joke should be understandable with sound muted.

## Advisory audit and acceptance

`plan audit` flags full long takes, absent spatial/result coverage for action, multiple independent POV jobs, dense active casts, multiple declared action units, late contact and slow camera wording. It reads declared metadata and cannot count hidden verbs in prose or see actual geometry. Findings invite judgment; they are not hard quality gates. No findings is not a pass. Structural validation, binding preflight, real moving-video inspection and listening remain separate checks.

Accept a short only when the actual retained media makes its objective, contact/result, subject identity, screen direction and payoff legible. Inspect contact frames for merged limbs, changing paws, floating feet and interpenetration. Check moving intervals for stutter or camera flips and listen to the final mix. If those tools are unavailable, report the evidence limit and keep the output under review.
