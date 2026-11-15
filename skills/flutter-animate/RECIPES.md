# Flutter animation recipes

Choose the matching recipe. Dart fragments below use `package:flutter/material.dart` and the motion constants from [SKILL.md](SKILL.md); integrate them into the existing widget's state and theme. Read the lifecycle and reduced-motion guidance there before adding a controller.

## Button press

Keep an existing `FilledButton`, `TextButton`, `IconButton`, or Cupertino button's feedback unless a custom press effect is requested. For custom scale feedback, wrap the actual button in `AnimatedScale`:

```dart
Widget pressFeedback(BuildContext context, bool pressed, Widget button) {
  final reduce = MediaQuery.disableAnimationsOf(context);
  return AnimatedScale(
    scale: pressed && !reduce ? 0.97 : 1.0,
    duration: reduce ? Duration.zero : const Duration(milliseconds: 120),
    curve: motionOut,
    child: button,
  );
}
```

The owning state supplies `pressed` from actual press down/up/cancel events without taking activation away from the button. Clear it when disabled or a drag wins. Retain the original hit target, keyboard activation, focus ring, and semantic label. Hover is a separate mouse state, never a side effect of touch down.

## Dropdown, popover, menu, select

Prefer `MenuAnchor`, `DropdownMenu`, `PopupMenuButton`, or the app's existing primitive. Their keyboard traversal, overlay placement, and focus return are part of the component.

For a custom panel, let a persistent controller run 0→1 on opening and reverse on closing. Drive `FadeTransition` and `ScaleTransition` (0.95→1.0, roughly 200 ms), with the scale alignment facing the trigger after collision placement. Anchor the overlay using `CompositedTransformTarget` / `CompositedTransformFollower` rather than storing screen coordinates that become stale during scroll. Keep it mounted until reverse completes; disable hidden input and restore trigger focus. Reduced motion uses the final pose or a brief fade.

## Tooltip

Use `Tooltip` and configure `waitDuration`, `showDuration`, or `exitDuration` only when needed. Preserve long-press discovery and semantics on touch. A custom toolbar may share a recently-open state so neighboring tooltips skip the initial delay; cancel pending timers when it closes or unmounts. If custom motion is necessary, use a small 0.97→1.0 scale and fade around 125 ms. Settle immediately with reduced motion.

## Dialog

Start with `showDialog` / `AlertDialog` or the app's Cupertino equivalent. Retain barrier semantics, back dismissal, focus traversal, and focus restoration.

For a requested custom transition, use `showGeneralDialog` with a localized `barrierLabel` when dismissible. Drive a centered 0.96→1.0 scale and fade from the route's animation (around 250 ms); the route owns its lifetime. Keep the scrim and content synchronized and remove scale in reduced motion. Choose a route that exposes separate reverse timing if needed; avoid wrapping an already-animated dialog in a second entrance.

## Drawer / bottom sheet

Prefer `Scaffold.drawer`, `showModalBottomSheet`, or `DraggableScrollableSheet` as appropriate. Built-in sheets coordinate drag, scroll, and dismissal.

On SDKs supporting `sheetAnimationStyle`, a standard modal sheet can honor reduced motion explicitly:

```dart
Future<void> openSheet(BuildContext context, Widget content) async {
  final reduce = MediaQuery.disableAnimationsOf(context);
  await showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    sheetAnimationStyle: reduce
        ? AnimationStyle.noAnimation
        : const AnimationStyle(
            duration: Duration(milliseconds: 300),
            reverseDuration: Duration(milliseconds: 200),
          ),
    builder: (context) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: content,
    ),
  );
}
```

For a wholly custom sheet, `SlideTransition` from `Offset(0, 1)` moves by its own height; a positive vertical offset goes down. Use the sheet curve from SKILL.md, and reverse toward the same edge. Test keyboard insets, bottom safe area, nested scrolling, and drag cancellation. Avoid stacking a custom slide on the framework sheet's transition.

## Toast / snackbar

Use `ScaffoldMessenger.showSnackBar` for standard transient messages. Retain its accessibility behavior and action handling. Keep display duration separate from entrance/exit duration.

For an existing custom toast overlay, use an explicit fade plus a short slide from its own edge, roughly 200–300 ms. Retarget from the current controller value when messages arrive rapidly. Keep outgoing entries alive through exit; cancel timers and dispose controllers when removed. Announce messages once rather than on every frame. Test stacked messages and remove outgoing input immediately when dismissal begins.

## Accordion / collapse

Use `ExpansionTile` or `ExpansionPanelList` first. For custom content whose natural height changes, `AnimatedSize` handles measurement:

```dart
Widget collapse(BuildContext context, bool expanded, Widget content) {
  final reduce = MediaQuery.disableAnimationsOf(context);
  return AnimatedSize(
    alignment: Alignment.topCenter,
    duration: reduce ? Duration.zero : const Duration(milliseconds: 200),
    curve: motionOut,
    child: expanded ? content : const SizedBox.shrink(),
  );
}
```

This variant removes collapsed content and its state immediately. When state must survive, use `ClipRect` plus `Align(heightFactor: ...)` or `SizeTransition` around a retained child. Explicitly exclude collapsed focus, input, and semantics. Layout changes are necessary here; profile large subtrees and check that expansion above the viewport does not unexpectedly move the reader.

## Group entrance / stagger

For an occasional onboarding group, use one controller and an `Interval` per item instead of one timer per widget. Start with offsets such as 0, 50, 90, 120 ms, leaving each item about 200 ms to settle. With a 320 ms timeline, the last interval starts at `120 / 320` and ends at 1.0. Bound the schedule so long lists do not delay late items indefinitely.

Drive a short fade and 8 logical pixel rise with each interval; convert to fractional units if using `SlideTransition`. Start once when the container enters the flow, retain stable item keys, and leave actions available. Reduced motion skips the stagger. Frequently scrolled lists show their items immediately.

## Hold to confirm

A hold is a deliberate interaction only when requested by the product. Supply an accessible confirmation alternative for keyboard and assistive technology users.

Use a controller with a linear two-second fill. Start on press down, cancel on pointer cancellation, drag loss, or release before completion, and reset over about 200 ms. Render the fill with `ClipRect` and `Align(widthFactor: progress)` in bounded button space. Fire the action once only after a completed hold while the same press remains active. Cancel on disabling or disposal. Reduced motion removes decorative scale but preserves accurate elapsed-time progress; never turn a timed confirmation into an immediate action.

## Tab indicator

Use `TabBar` and `TabController`; their indicator, selection, semantics, and `TabBarView` coordination belong together. Customize `indicator` and label styles before replacing the component.

For a segmented control with a moving pill, measure actual tab bounds, then animate the pill under the existing interactive controls with `AnimatedAlign` or a small positioned layout animation, around 200–250 ms. Test variable labels, text scaling, and RTL. If a visual duplicate is required for a reveal effect, make it `IgnorePointer` and `ExcludeSemantics` so it creates no duplicate controls. Reduced motion places the indicator directly at the selected tab.

## Scroll reveal

Use only for occasional explanatory content. Trigger once from the existing visibility/scroll mechanism, not on every `build` or repeated scroll-by. Flutter core has no browser intersection observer; derive viewport visibility through the app's scroll/sliver geometry or reuse an installed visibility observer.

Fade with a short rise, leaving content available if visibility detection fails. Store reveal state by stable item identity so virtualization does not replay it. With reduced motion, render immediately and skip the observer-driven entrance. Keep functional dashboards and routine lists visible without waiting for a reveal.

## Drag to dismiss / spring return

Use `Dismissible` for list rows and built-in draggable sheets for sheets. A dismissible needs a stable item key and removal from the backing collection in `onDismissed`; use `confirmDismiss` for an asynchronous decision. Supply an accessible non-swipe action where needed.

For a custom surface, use Flutter's drag recognizers and gesture arena. On drag start, stop the settling simulation and keep its current position. Track one drag sequence; use logical pixel deltas and release velocity from `DragEndDetails.velocity.pixelsPerSecond`. Apply increasing resistance beyond the allowed range and decide dismissal using distance and velocity in the outward direction. Gesture cancellation settles back without firing dismissal.

This fragment is a return-to-rest helper for an owning State. `position` is an `AnimationController.unbounded(vsync: this)` storing **logical pixels**; render `position.value` with `Transform.translate` through an `AnimatedBuilder`. Create/dispose it with the State. Import `package:flutter/physics.dart`.

```dart
void settlePosition({
  required AnimationController position,
  required double targetPixels,
  required double velocityPixelsPerSecond,
  required bool reduceMotion,
}) {
  if (reduceMotion) {
    position.value = targetPixels;
    return;
  }
  position.animateWith(
    SpringSimulation(
      SpringDescription.withDampingRatio(
        mass: 1.0,
        stiffness: 300.0,
        ratio: 1.0,
      ),
      position.value,
      targetPixels,
      velocityPixelsPerSecond,
    ),
  );
}
```

This critically damped spring is a starting point without bounce; tune on a device. For a normalized 0–1 controller instead, divide pixel position and velocity by the travel extent, guarding zero extent. A spring does not preserve velocity automatically across new simulations: capture `position.velocity` before stopping when retargeting, or supply the current release velocity. A bounded controller clips overshoot; unbounded values need explicit visual limits when appropriate.

## Crossfade that remains visually busy

Use `AnimatedSwitcher` with `ValueKey(stateIdentity)` for distinct states, or `AnimatedCrossFade` when two retained states and a size transition are intended. Test rapid A→B→A replacement: outgoing switcher children can overlap. If overlap reduces readability, fade out then swap and fade in with an explicit controller, or update instantly for frequent changes.

Prefer a readable transition before adding blur. `ImageFiltered` can blur the local child if a designed effect calls for it; `BackdropFilter` affects content behind it and has different cost. Profile on the target renderer and device, keep the affected region small, and remove decorative blur with reduced motion.

## Programmatic control without a package

Use `AnimationController` with an `AnimatedBuilder` or transition widgets. The controller coordinates time; the tween maps values; the curve shapes progress. Keep a stable child outside the builder, reverse from the current value, and use status or cancellable completion handling for exit. Flutter ticks still depend on UI-isolate scheduling, so heavy synchronous work can stall these animations. Verify frame timing in profile mode rather than assuming a controller makes motion independent of application work.
