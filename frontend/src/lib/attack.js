/**
 * Turning a flat detection list into matrix cells.
 *
 * Lives here rather than beside the grid component because it is the piece
 * with a rule in it worth testing on its own: a detection on `T1059.001` is a
 * detection on the `T1059` cell, since sub-techniques do not get cells of
 * their own (679 placed techniques collapse to 211 parents — the difference
 * between a matrix and a wall). A cell therefore has to carry both halves, and
 * a parent detected *only* through its children must still shade.
 */
export function foldDetections(detections = []) {
  const byParent = new Map();

  for (const detection of detections) {
    const entry = byParent.get(detection.parent_id) ?? {
      direct: 0,
      viaSubs: 0,
      unverified: false,
      subs: [],
      detections: [],
    };
    entry.detections.push(detection);
    // One unverified child is enough to mark the cell. The alternative —
    // marking only when every detection is unverified — would hide the case
    // this project cares about most.
    entry.unverified = entry.unverified || !detection.verified;
    if (detection.sub_technique) {
      entry.viaSubs += detection.count;
      entry.subs.push(detection);
    } else {
      entry.direct += detection.count;
    }
    byParent.set(detection.parent_id, entry);
  }

  for (const entry of byParent.values()) {
    entry.total = entry.direct + entry.viaSubs;
  }
  return byParent;
}
