---
name: flutter-animate
description: Build Flutter animations for widget state changes, entrances and exits, route transitions, and interruptible gestures. Use when asked to add motion or implement a transition in a Flutter app.
---

# Flutter animations

Implement the requested motion. Choose the approach, explain the reason briefly, and write the code. This skill uses Flutter's animation APIs; it does not require the similarly named `flutter_animate` package.

## 1. Decide whether motion helps

Inspect the affected widget, theme, existing motion tokens, SDK constraints, and dependencies before choosing an API. Extend the app's conventions, including Material or Cupertino transitions, rather than introducing a parallel motion system.

| Frequency | Motion budget |
| --- | --- |
| Very frequent commands, typing, repeated list navigation | Instant state changes; preserve useful platform feedback |
| Frequent taps or hover | Brief, subtle feedback |
| Occasional dialogs, menus, sheets | Short transitions that explain the change |
| Onboarding or rare success | More expressive motion if it serves the task |

Name the purpose: feedback, spatial continuity, state indication, smoothing a content change, explanation, or rare delight. If motion only delays the task, implement an instant change and explain why. Keep information stationary while the user reads or manipulates it. Keyboard activation must remain as responsive as touch and retain focus feedback.

## 2. Choose the smallest suitable API

| Need | Start with |
| --- | --- |
| Standard button, menu, tooltip, dialog, sheet, tab, navigation | Existing Material/Cupertino widget or route transition |
| Animate a property toward a new state | `AnimatedScale`, `AnimatedOpacity`, `AnimatedAlign`, or a focused `TweenAnimationBuilder` |
| Replace content, including its outgoing state | `AnimatedSwitcher` with stable keys distinguishing states |
| Coordinate entrance, exit, reverse, or stagger | `AnimationController` with `FadeTransition`, `SlideTransition`, `ScaleTransition`, or `AnimatedBuilder` |
| Gesture follows a finger then settles | Existing draggable widget first; otherwise controller plus `SpringSimulation` |
| Move the same visual between routes | `Hero` with matching tags and compatible bounds |

Use an installed animation package when it fits the app; a fade alone does not justify a new dependency. Preserve built-in focus, semantics, dismissal, and gesture behavior when customizing standard components.

## 3. Choose what changes

- Prefer paint transforms for movement that should leave layout unchanged. `Transform.translate` uses logical pixels; `SlideTransition` uses fractions of the child's size. For horizontal semantic direction, supply `textDirection` where supported or resolve directional alignment.
- Start a surface near its final scale, usually 0.95–0.97, with a fade. Use the trigger-facing `alignment` for an anchored menu; keep unanchored dialogs centered.
- Use layout animation when surrounding content must move: `AnimatedSize`, `SizeTransition`, or an existing expansion widget. Keep the animated subtree small and check scroll stability.
- Use `FadeTransition` for an explicit fade rather than rebuilding `Opacity` on every tick. Opacity, clipping, blur, and shadows can still cost raster work; transforms and fades have no universal GPU-only guarantee in Flutter.
- Keep stable content in `AnimatedBuilder.child`. Localize rebuilds; move expensive synchronous work off the UI isolate. Add `RepaintBoundary` only when profiling shows it isolates useful repaint work.

## 4. Set timing or physics

Prefer existing motion tokens and framework component defaults. For custom motion without tokens, these are starting points, not a replacement for platform behavior:

```dart
import 'package:flutter/animation.dart';

const motionOut = Cubic(0.23, 1.0, 0.32, 1.0);
const motionInOut = Cubic(0.77, 0.0, 0.175, 1.0);
const motionSheet = Cubic(0.32, 0.72, 0.0, 1.0);
```

| Motion | Curve | Duration |
| --- | --- | --- |
| Press feedback | `motionOut` | 100–160 ms |
| Tooltip or small popover | `motionOut` | 125–200 ms |
| Menu or content replacement | `motionOut` | 150–250 ms |
| Dialog or sheet | Existing route curve, otherwise `motionOut` / `motionSheet` | 200–500 ms |
| Moving between on-screen positions | `motionInOut` | 150–250 ms |
| Determinate progress or hold fill | `Curves.linear` | Actual task/hold duration |

Most custom UI transitions should finish within 300 ms. Reserve longer motion for large surfaces or explanation. Entrances should respond immediately rather than spend their first frames accelerating slowly. Keep decorative bounce rare.

For a gesture, use a spring with position and velocity in the same units. Flutter's `SpringDescription` uses mass, stiffness, and damping, not a duration/bounce pair. Read the drag recipe before implementing custom physics.

## 5. Make interruption and exit work

- Retarget implicit animations through new values. For an explicit controller, call `forward()`, `reverse()`, or `animateTo()` from its current value; resetting to zero causes jumps. A new spring needs the current position and velocity.
- Keep an outgoing surface mounted until its reverse completes. Use route lifecycle, `AnimatedSwitcher`, or a dismissal status handler. Guard stale completion callbacks when an exit is canceled by reopening.
- Create controllers in `State.initState` with a ticker provider and dispose them in `State.dispose`. Use `SingleTickerProviderStateMixin` for one controller over that State's lifetime, otherwise `TickerProviderStateMixin`. Dispose owned `CurvedAnimation` objects too.
- Keep controllers out of `build`. Update configuration in lifecycle methods when widget inputs change. For cancellable async animation sequences, await `.orCancel`, handle `TickerCanceled`, and check `mounted` before updating UI after other awaits.
- Preserve state with stable keys. `AnimatedSwitcher` can keep several outgoing children during rapid replacement; use a reversible single-child transition when that overlap would be confusing.

## 6. Ship accessibility with the motion

Read `MediaQuery.disableAnimationsOf(context)` in a dependency-aware location such as `build` or `didChangeDependencies`. When true, remove decorative translation, scale, bounce, and stagger; show the final state immediately or use a brief fade only when useful. Handle the preference changing during an active animation by settling it. Controller `AnimationBehavior.normal` alone is not a complete reduced-motion design; unbounded controllers default to preserving animation.

An invisible widget can still receive input. Coordinate `IgnorePointer`, focus eligibility, and semantics with whether a surface is available, and return focus to the trigger when it closes. Preserve accessible labels and keyboard actions. Progress that communicates real work must still communicate state when decorative motion is disabled.

Use `MouseRegion` or standard control hover callbacks for mouse hover; keep touch feedback on press. Keyboard focus gets its own visible state. A custom press resets on cancellation, drag loss, disabling, and release; keep the normal button's activation and semantics.

## References

| Read when | Reference |
| --- | --- |
| Implementing a common component or custom spring | [RECIPES.md](RECIPES.md) — Flutter recipes, lifecycle, and gesture units |
| Checking API choices against the project's SDK | [Flutter animation overview](https://docs.flutter.dev/ui/animations/overview), [AnimationController](https://api.flutter.dev/flutter/animation/AnimationController-class.html) |
| Measuring rebuild, layout, or raster cost | [Flutter performance practices](https://docs.flutter.dev/perf/best-practices) |

## Verify and deliver

Run formatting and analysis on changed Dart code using the project's Flutter tooling. For behavior involving exits, gestures, or async completion, run relevant widget tests covering rapid reversal, cancellation/disposal, and reduced motion. Use bounded pumps for repeating animations. Check the visual result in profile mode on a target device: responsiveness, keyboard/focus, touch cancellation, large text, RTL where relevant, and frame timing on the target refresh rate. Slow playback helps inspect choreography; normal speed determines whether it feels responsive.

Deliver the implementation with a brief note naming the purpose, chosen widget/controller, curve and timing or spring, checks performed, and any visual behavior still requiring device review.
