import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Eye, EyeOff, Users, X } from "lucide-react";
import { clsx } from "clsx";
import { api, thumbnailUrl, type HiddenGroup, type PersonGroup, type PersonSummary } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../../components/Page";
import { useScrollRestore } from "../../hooks/useScrollRestore";
import { plural } from "../../lib/format";
import { FaceStack } from "./FaceStack";
import { groupNames, ignoreConfirmText, personName } from "./names";

const PERSON_GRID = "grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-4";
const GROUP_GRID = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4";

// People list view (route: /people)
export function People() {
  const { scrollRef, restoreScroll } = useScrollRestore("people");
  const queryClient = useQueryClient();

  const personsQuery = useQuery({
    queryKey: queryKeys.persons,
    queryFn: () => api.getPersons({ page_size: 200 }),
  });
  const groupsQuery = useQuery({
    queryKey: [...queryKeys.personGroups, { min_photos: 3 }],
    queryFn: () => api.getPersonGroups({ min_photos: 3 }),
  });
  const { data: hiddenGroups = [] } = useQuery({
    queryKey: queryKeys.hiddenGroups,
    queryFn: api.getHiddenGroups,
  });
  const persons = personsQuery.data ?? [];

  useEffect(() => {
    if (!personsQuery.isLoading && !groupsQuery.isLoading && persons.length > 0) {
      restoreScroll();
    }
  }, [personsQuery.isLoading, groupsQuery.isLoading, persons.length, restoreScroll]);

  const handleIgnore = async (person: PersonSummary) => {
    if (!window.confirm(ignoreConfirmText(person, "below"))) return;
    await api.ignorePerson(person.person_id);
    // Also refreshes the ignored list, which is keyed under persons.
    void queryClient.invalidateQueries({ queryKey: queryKeys.persons });
  };

  if (personsQuery.isLoading) return <PageSpinner />;
  if (personsQuery.error) return <ErrorState error={personsQuery.error} />;
  if (persons.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="No people detected yet"
        hint="Face detection will run during photo processing"
      />
    );
  }

  return (
    <div ref={scrollRef} className="overflow-y-auto h-full">
      <PageHeader>
        <PageTitle count={`${persons.length} ${plural(persons.length, "person")}`}>People</PageTitle>
      </PageHeader>

      {/* Together section, on top */}
      {(groupsQuery.isLoading || (groupsQuery.data?.length ?? 0) > 0 || hiddenGroups.length > 0) && (
        <TogetherSection
          groups={groupsQuery.data}
          loading={groupsQuery.isLoading}
          hiddenGroups={hiddenGroups}
        />
      )}

      {/* All people */}
      <div className="px-4 py-3 border-t border-b border-gray-100">
        <h2 className="text-base font-semibold text-gray-700">All People</h2>
      </div>

      <div className={clsx(PERSON_GRID, "p-4")}>
        {persons.map((person) => (
          <PersonCard key={person.person_id} person={person} onIgnore={() => handleIgnore(person)} />
        ))}
      </div>

      <IgnoredPeople />
    </div>
  );
}

function TogetherSection({
  groups,
  loading,
  hiddenGroups,
}: {
  groups: PersonGroup[] | undefined;
  loading: boolean;
  hiddenGroups: HiddenGroup[];
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showHidden, setShowHidden] = useState(false);

  // Hiding removes just that tile from the section: the people themselves
  // stay visible on the page and in their photos.
  const setHidden = async (personIds: number[], hidden: boolean) => {
    await (hidden ? api.hideGroup(personIds) : api.unhideGroup(personIds));
    void queryClient.invalidateQueries({ queryKey: queryKeys.personGroups });
    void queryClient.invalidateQueries({ queryKey: queryKeys.hiddenGroups });
  };

  const count = groups?.length ?? 0;
  return (
    <>
      <div className="px-4 py-3 border-b border-gray-100">
        <h2 className="text-base font-semibold text-gray-700">
          Together
          {!loading && (
            <span className="ml-2 text-gray-400 font-normal text-sm">
              {count} {plural(count, "group")}
            </span>
          )}
        </h2>
      </div>

      {loading ? (
        <div className={GROUP_GRID}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-xl overflow-hidden border border-gray-100">
              <div className="aspect-video bg-gray-100 animate-pulse" />
              <div className="p-3 flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-gray-100 animate-pulse" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3.5 bg-gray-100 rounded animate-pulse w-3/4" />
                  <div className="h-3 bg-gray-100 rounded animate-pulse w-1/2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className={GROUP_GRID}>
          {groups
            ?.filter((group) => group.persons.length >= 2)
            .map((group) => {
              const ids = group.persons.map((p) => p.person_id);
              return (
                <div key={ids.join(",")} className="relative group">
                  <button
                    onClick={() => navigate(`/people/together/${ids.join(",")}`)}
                    className="w-full bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left"
                  >
                    <div className="aspect-video bg-gray-100 relative overflow-hidden">
                      {group.cover_photo ? (
                        <img
                          src={thumbnailUrl(group.cover_photo.file_hash, 600)}
                          alt=""
                          loading="lazy"
                          decoding="async"
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <Users className="w-12 h-12 text-gray-300" />
                        </div>
                      )}
                    </div>
                    <div className="p-3 flex items-center gap-3">
                      <FaceStack persons={group.persons} />
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{groupNames(group.persons)}</p>
                        <p className="text-xs text-gray-400">{group.shared_photo_count} photos together</p>
                      </div>
                    </div>
                  </button>
                  {/* Sits outside the nav button: button-in-button is invalid HTML */}
                  <button
                    onClick={() => setHidden(ids, true)}
                    className="absolute top-2 right-2 p-1.5 rounded-full bg-white/90 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity hover:bg-white shadow-sm"
                    title="Hide this group"
                  >
                    <X className="w-4 h-4 text-gray-500" />
                  </button>
                </div>
              );
            })}
        </div>
      )}

      {/* Hidden tiles: restore row */}
      {hiddenGroups.length > 0 && (
        <div className="px-4 pb-4">
          <button
            onClick={() => setShowHidden((v) => !v)}
            className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            <EyeOff className="w-4 h-4" />
            {hiddenGroups.length} hidden {plural(hiddenGroups.length, "group")}
            <ChevronDown className={clsx("w-4 h-4 transition-transform", showHidden && "rotate-180")} />
          </button>
          {showHidden && (
            <div className="flex flex-wrap gap-2 mt-3">
              {hiddenGroups.map((g) => (
                <div
                  key={g.group_key}
                  className="flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-full border border-gray-200 bg-white"
                >
                  <FaceStack persons={g.persons} size="w-6 h-6" overlap="-space-x-1.5" ring="ring-1" />
                  <span className="text-xs text-gray-600">
                    {g.persons.length ? groupNames(g.persons) : g.group_key}
                  </span>
                  <button
                    onClick={() => setHidden(g.persons.map((p) => p.person_id), false)}
                    className="p-0.5 rounded-full hover:bg-gray-100 transition-colors"
                    title="Show this group again"
                  >
                    <Eye className="w-3.5 h-3.5 text-gray-400" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Avatar({ person, alt, className }: { person: PersonSummary; alt: string; className?: string }) {
  return person.face_thumbnail_url ? (
    <img
      src={person.face_thumbnail_url}
      alt={alt}
      loading="lazy"
      decoding="async"
      className={clsx("w-20 h-20 rounded-full object-cover", className)}
    />
  ) : (
    <div className="w-20 h-20 rounded-full bg-gray-200 flex items-center justify-center">
      <Users className="w-8 h-8 text-gray-400" />
    </div>
  );
}

function PersonCard({ person, onIgnore }: { person: PersonSummary; onIgnore: () => void }) {
  const navigate = useNavigate();
  const open = () => navigate(`/people/${person.person_id}`);
  return (
    // A div, not a <button>: the Ignore button nests inside, and button-in-button is invalid HTML
    <div
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter") open();
      }}
      className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-gray-50 transition-colors group relative cursor-pointer"
    >
      <Avatar
        person={person}
        alt={person.name || ""}
        className="group-hover:ring-2 ring-primary-300 transition-all"
      />
      <div className="text-center">
        <p className="text-sm font-medium truncate max-w-[100px]">{personName(person)}</p>
        <p className="text-xs text-gray-400">{person.photo_count} photos</p>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onIgnore();
        }}
        className="absolute top-1 right-1 p-1 rounded-full bg-white/80 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200"
        title="Ignore"
      >
        <EyeOff className="w-3 h-3 text-gray-400" />
      </button>
    </div>
  );
}

/** Collapsible list of ignored people, fetched the first time it is opened. */
function IgnoredPeople() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data: ignored } = useQuery({
    queryKey: queryKeys.ignoredPersons,
    queryFn: api.getIgnoredPersons,
    enabled: open,
  });

  const handleUnignore = async (personId: number) => {
    await api.unignorePerson(personId);
    queryClient.setQueryData<PersonSummary[]>(queryKeys.ignoredPersons, (prev) =>
      prev?.filter((p) => p.person_id !== personId)
    );
    void queryClient.invalidateQueries({ queryKey: queryKeys.persons });
  };

  return (
    <div className="border-t border-gray-100">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 flex items-center gap-2 text-sm text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
      >
        <EyeOff className="w-4 h-4" />
        Ignored people
        <ChevronDown className={clsx("w-4 h-4 ml-auto transition-transform", open && "rotate-180")} />
      </button>

      {open && ignored && ignored.length > 0 && (
        <div className={clsx(PERSON_GRID, "px-4 pb-4")}>
          {ignored.map((person) => (
            <div
              key={person.person_id}
              className="flex flex-col items-center gap-2 p-3 rounded-xl opacity-50 hover:opacity-100 transition-opacity relative group"
            >
              <Avatar person={person} alt="" className="grayscale" />
              <div className="text-center">
                <p className="text-sm font-medium truncate max-w-[100px] text-gray-400">{personName(person)}</p>
                <p className="text-xs text-gray-300">{person.photo_count} photos</p>
              </div>
              <button
                onClick={() => handleUnignore(person.person_id)}
                className="absolute top-1 right-1 p-1 rounded-full bg-white/80 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200"
                title="Un-ignore"
              >
                <Eye className="w-3 h-3 text-gray-500" />
              </button>
            </div>
          ))}
        </div>
      )}
      {open && ignored && ignored.length === 0 && (
        <p className="px-4 pb-4 text-sm text-gray-300">No ignored people</p>
      )}
    </div>
  );
}
