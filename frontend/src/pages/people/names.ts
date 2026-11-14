import type { PersonSummary } from "../../api/client";

/** A person's name, or "Person 12" while they are still unnamed. */
export function personName(p: PersonSummary): string {
  return p.name || `Person ${p.person_id}`;
}

/** "Ann & Bob", or "Ann, Bob & Cas" for larger groups. */
export function groupNames(persons: PersonSummary[]): string {
  if (persons.length <= 2) return persons.map(personName).join(" & ");
  return persons.slice(0, -1).map(personName).join(", ") + " & " + personName(persons[persons.length - 1]!);
}

/** Confirmation text for hiding a person; `restoreHint` says where to undo it. */
export function ignoreConfirmText(person: PersonSummary, restoreHint: string): string {
  return (
    `Hide ${personName(person)} (${person.photo_count} photos) from the people list?\n\n` +
    `The photos stay in your library. You can restore them under "Ignored people" ${restoreHint}.`
  );
}
