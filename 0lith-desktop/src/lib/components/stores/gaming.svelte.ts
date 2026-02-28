let enabled = $state(false);

export function isGaming(): boolean {
  return enabled;
}

export function setGaming(v: boolean): void {
  enabled = v;
}
