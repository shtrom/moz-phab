# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
from typing import Dict, List

from mozphab import environment
from mozphab.commits import Commit
from mozphab.conduit import conduit
from mozphab.config import config
from mozphab.exceptions import Error
from mozphab.helpers import (
    BLOCKING_REVIEWERS_RE,
    augment_commits_from_body,
    move_drev_to_original,
    prompt,
    strip_differential_revision,
    update_commit_title_previews,
)
from mozphab.logger import logger
from mozphab.repository import Repository
from mozphab.spinner import wait_message
from mozphab.telemetry import telemetry

PHABRICATOR_URLS = {
    "https://phabricator.services.mozilla.com/": "Phabricator",
    "https://phabricator-dev.allizom.org/": "Phabricator-Dev",
}


def morph_blocking_reviewers(commits: List[Commit]):
    """Automatically fix common typo by replacing r!user with r=user!"""

    def morph_reviewer(matchobj):
        if matchobj.group(1) == "r!":
            nick = matchobj.group(2)

            # strip trailing , or . so we can put it back later
            if nick[-1] in (",", "."):
                suffix = nick[-1]
                nick = nick[:-1]
            else:
                suffix = ""

            # split on comma to support r!a,b -> r=a!,b!
            return "r=%s%s" % (
                ",".join(["%s!" % n.rstrip("!") for n in nick.split(",")]),
                suffix,
            )
        else:
            return matchobj.group(0)

    for commit in commits:
        commit.title = BLOCKING_REVIEWERS_RE.sub(morph_reviewer, commit.title)


def amend_revision_url(body: str, new_url: str) -> str:
    """Append or replace the Differential Revision URL in a commit body."""
    body = strip_differential_revision(body)
    if body:
        body += "\n"
    body += "\nDifferential Revision: %s" % new_url
    return body


def show_commit_stack(
    commits: List[Commit],
    args: argparse.Namespace,
    validate: bool = True,
    show_rev_urls: bool = False,
    show_updated_only: bool = False,
):
    """Log the commit stack in a human readable form."""

    # keep output in columns by sizing the action column to the longest rev + 1 ("D")
    max_len = (
        max(len(str(commit.rev_id or "")) for commit in commits) + 1 if commits else ""
    )
    action_template = "(%" + str(max_len) + "s)"

    if validate:
        # preload all revisions
        ids = [commit.rev_id for commit in commits if commit.rev_id is not None]
        if ids:
            with wait_message("Loading existing revisions..."):
                revisions = conduit.get_revisions(ids=ids)
                revisions = {revision["id"]: revision for revision in revisions}

            # preload diffs
            with wait_message("Loading diffs..."):
                diff_phids = [r["fields"]["diffPHID"] for r in revisions.values()]
                diffs = conduit.get_diffs(phids=diff_phids) if diff_phids else {}

    for commit in reversed(commits):
        if show_updated_only and not commit.submit:
            continue

        revision_is_closed = False
        revision_is_wip = False
        bug_id_changed = False
        is_author = True
        revision = None

        if commit.rev_id is not None:
            action = action_template % f"D{commit.rev_id}"

            if validate and (revision := revisions.get(commit.rev_id)):
                fields = revision["fields"]

                # WIP if either in changes-planned state, or if the revision has the
                # `draft` flag set.
                revision_is_wip = bool(
                    fields["status"]["value"] == "changes-planned" or fields["isDraft"]
                )

                # Check if target bug ID is the same as in the Phabricator revision.
                bug_id_changed = bool(
                    fields.get("bugzilla.bug-id")
                    and commit.bug_id != fields["bugzilla.bug-id"]
                )

                # Check if revision is closed.
                revision_is_closed = bool(fields["status"]["closed"])

                # Check if comandeering is required.
                with wait_message("Figuring out who you are..."):
                    whoami = conduit.whoami()
                if "authorPHID" in fields and fields["authorPHID"] != whoami["phid"]:
                    is_author = False

                # Any reviewers added to a revision without them?
                reviewers_added = bool(
                    not revision["attachments"]["reviewers"]["reviewers"]
                    and commit.reviewers["granted"]
                )

                # If SHA1 hasn't changed
                # and we're not changing the WIP or draft status
                # and we're not adding reviewers to a revision without reviewers
                # and we're not changing the bug ID
                # then don't submit.
                diff_phid = fields["diffPHID"]
                diff_commits = diffs[diff_phid]["attachments"]["commits"]["commits"]
                sha1_changed = bool(
                    not diff_commits or commit.node != diff_commits[0]["identifier"]
                )
                if (
                    not sha1_changed
                    and commit.wip == revision_is_wip
                    and not reviewers_added
                    and not bug_id_changed
                    and not revision_is_closed
                    and not args.force
                ):
                    commit.submit = False

        else:
            action = action_template % "New"

        logger.info("%s %s %s", action, commit.name, commit.title_preview)
        if validate:
            if not commit.submit:
                logger.info(
                    " * This revision has not changed and will not be submitted."
                )
                continue

            if revision:
                if not commit.wip and revision_is_wip:
                    logger.warning(
                        '!! "Changes Planned" status will change to "Request Review"'
                    )
                if commit.wip and not revision_is_wip:
                    logger.warning(
                        '!! "Request Review" status will change to "Changes Planned"'
                    )

            if bug_id_changed:
                logger.warning(
                    "!! Bug ID in Phabricator revision will change from %s to %s",
                    revision["fields"]["bugzilla.bug-id"],
                    commit.bug_id,
                )

            if not is_author:
                logger.warning(
                    "!! You don't own this revision. Normally, you should only\n"
                    '   update revisions you own. You can "Commandeer" this\n'
                    "   revision from the web interface if you want to become\n"
                    "   the owner."
                )

            if revision_is_closed:
                logger.warning(
                    "!! This revision is closed!\n"
                    "   It will be reopened if submission proceeds.\n"
                    "   You can stop now and refine the stack range."
                )

            if not commit.bug_id:
                logger.warning("!! Missing Bug ID")

            if commit.bug_id_orig and commit.bug_id != commit.bug_id_orig:
                logger.warning(
                    "!! Bug ID changed from %s to %s",
                    commit.bug_id_orig,
                    commit.bug_id,
                )

            if not commit.has_reviewers and args.command != "uplift":
                logger.warning("!! Missing reviewers")
                if commit.wip:
                    logger.warning(
                        '   It will be submitted as "Changes Planned".\n'
                        "   Run submit again with --no-wip to prevent this."
                    )

        if show_rev_urls and commit.rev_id:
            logger.warning("-> %s/D%s", conduit.repo.phab_url, commit.rev_id)


def make_blocking(reviewers: List[str]) -> List[str]:
    """Convert a list of reviewer strings into a list of blocking reviewer strings."""
    return ["%s!" % r.rstrip("!") for r in reviewers]


def remove_duplicates(reviewers: List[str]) -> List[str]:
    """Remove all duplicate items from the list.

    Args:
        reviewers: list of strings representing IRC nicks of reviewers.

    Returns: list of unique reviewers.

    Duplicates with excalamation mark are preferred.
    """
    unique = []
    nicks = []
    for reviewer in reviewers:
        nick = reviewer.lower().strip("!")
        if reviewer.endswith("!") and nick in nicks:
            nicks.remove(nick)
            unique = [r for r in unique if r.lower().strip("!") != nick]

        if nick not in nicks:
            nicks.append(nick)
            unique.append(reviewer)

    return unique


def update_commits_from_args(commits: List[Commit], args: argparse.Namespace):
    """Modify commit description based on args and configuration.

    Args:
        commits: list of Commits representing the commits in commit stack
        args: argparse.Namespace object. In this function we're using
            following attributes:
            * reviewer - list of strings representing reviewers
            * blocker - list of string representing blocking reviewers
            * bug - an integer representing bug id in Bugzilla

    Command args always overwrite commit desc.
    Overwriting reviewers rules
    (The "-r" are loaded into args.reviewer and "-R" into args.blocker):
        a) Recognize `r=` and `r?` from commit message title.
        b) Modify reviewers only if `-r` or `-R` is used in call arguments.
        c) Add new reviewers using `r=`.
        d) Do not modify reviewers already provided in the title (`r?` or `r=`).
        e) Delete reviewer if `-r` or `-R` is used and the reviewer is not mentioned.

    If no reviewers are provided by args and an `always_blocking` flag is set
    change all reviewers in title to blocking.
    """

    # Build list of reviewers from args.
    reviewers = list(set(args.reviewer)) if args.reviewer else []

    # Order might be changed here `list(set(["one", "two"])) == ['two', 'one']`
    reviewers.sort()
    blockers = [r.rstrip("!") for r in args.blocker] if args.blocker else []

    # User might use "-r <nick>!" to provide a blocking reviewer.
    # Add all such blocking reviewers to blockers list.
    blockers += [r.rstrip("!") for r in reviewers if r.endswith("!")]
    blockers = list(set(blockers))
    blockers.sort()

    # Remove blocking reviewers from reviewers list
    reviewers_no_flag = [r.strip("!") for r in reviewers]
    reviewers = [r for r in reviewers_no_flag if r.lower() not in blockers]

    # Add all blockers to reviewers list. Reviewers list will contain a list
    # of all reviewers where blocking ones are marked with the "!" suffix.
    reviewers += make_blocking(blockers)
    reviewers = remove_duplicates(reviewers)
    lowercase_reviewers = [r.lower() for r in reviewers]
    lowercase_blockers = [r.lower() for r in blockers]

    for commit in commits:
        if reviewers:
            # Only the reviewers mentioned in command line args will remain.
            # New reviewers will be marked as "granted" (r=).
            granted = reviewers.copy()
            requested = []

            # commit["reviewers"]["request|"] is a list containing reviewers
            # provided in commit's title with an r? mark.
            for reviewer in commit.reviewers["request"]:
                r = reviewer.strip("!")
                # check which request reviewers are provided also via -r
                if r.lower() in lowercase_reviewers:
                    requested.append(r)
                    granted.remove(r)
                # check which request reviewers are provided also via -R
                elif r.lower() in lowercase_blockers:
                    requested.append("%s!" % r)
                    granted.remove("%s!" % r)
        else:
            granted = commit.reviewers.get("granted", [])
            requested = commit.reviewers.get("request", [])

        commit.reviewers = {"granted": granted, "request": requested}

        if args.bug:
            # Bug ID command arg used.
            commit.bug_id = args.bug

        # Mark a commit as WIP if --wip is provided, or if the commit does not have
        # any reviewers.  This is in addition to checking for the WIP: prefix in
        # helpers.augment_commits_from_body()
        if not args.no_wip and (args.wip or not commit.has_reviewers):
            commit.wip = True
        elif commit.wip is None:
            commit.wip = False

    # Honour config setting to always use blockers
    if not reviewers and config.always_blocking:
        for commit in commits:
            commit.reviewers = {
                "request": make_blocking(commit.reviewers["request"]),
                "granted": make_blocking(commit.reviewers["granted"]),
            }


def update_commits_for_uplift(
    commits: List[Commit], revisions: Dict[int, dict], repo: Repository
):
    """Prepares a set of commits for uplifting."""
    for commit in commits:
        # Clear all reviewers from the revision.
        commit.reviewers = {
            "granted": [],
            "request": [],
        }

        # Skip when updating an existing revision on the uplift repo.
        revision = revisions.get(commit.rev_id)
        if not revision or revision["fields"]["repositoryPHID"] == repo.phid:
            continue

        # When uplifting, ensure the `Differential Revision` line is properly
        # moved, and that `rev-id` is updated to not point at the original revision.
        commit.body, commit.rev_id = move_drev_to_original(
            commit.body,
            commit.rev_id,
        )


def update_revision_description(
    transactions: List[dict], commit: Commit, revision: dict
):
    # Appends differential.revision.edit transaction(s) to `transactions` if
    # updating the commit title and/or summary is required.

    if commit.title != revision["fields"]["title"]:
        transactions.append({"type": "title", "value": commit.title})

    # The Phabricator API will refuse the new summary value if we include the
    # "Differential Revision:" keyword in the summary body.
    local_body = strip_differential_revision(commit.body).strip()
    remote_body = strip_differential_revision(revision["fields"]["summary"]).strip()
    if local_body != remote_body:
        transactions.append({"type": "summary", "value": local_body})


def update_revision_bug_id(transactions: List[dict], commit: Commit, revision: dict):
    # Appends differential.revision.edit transaction(s) to `transactions` if
    # updating the commit bug-id is required.
    if commit.bug_id and commit.bug_id != revision["fields"]["bugzilla.bug-id"]:
        transactions.append({"type": "bugzilla.bug-id", "value": commit.bug_id})


def local_uplift_if_possible(
    args: argparse.Namespace, repo: Repository, commits: List[Commit]
) -> bool:
    """If possible, rebase local repository commits onto the target uplift train.

    Uplifts will be performed if the `--no-rebase` argument is not
    passed, if the local repository has a corresponding unified head
    for the uplift train, and if the revset being submitted is not
    already descendant from the target unified head.

    Returns a `bool` indicating if the `commits` should avoid making local
    repository changes to reflect new Phabricator revisions. If `True`,
    local commits may be amended to reflect their state on Phabricator,
    for example to add the `Differential Revision` line. If `False`, the
    local repository commits should not be updated by `moz-phab`.
    """
    if args.no_rebase:
        # If args tell us not to do a rebase, do not make any local changes and
        # return without rebasing. This is the same as submitting an uplift where
        # the original patch is sent to Phabricator without any modifications.
        # In this case we want to avoid local amendments to commits.
        return True

    # Try and find a local repo identifier (hg bookmark, git remote branch) to rebase
    # our revset onto.
    unified_head = repo.map_callsign_to_unified_head(args.train)

    if not unified_head:
        # If we didn't find a unified head, we intend to submit an uplift without
        # modifying the local repo state via a rebase.
        logger.warning(
            f"Couldn't find a head for {args.train} in version control, "
            "submitting without rebase."
        )
        return True

    if not repo.is_descendant(unified_head):
        # If we found a head to rebase onto and the commit isn't already a descendant
        # of our target identifier, uplift the commits onto the unified head.
        with wait_message(f"Rebasing commits onto {unified_head}"):
            commits = repo.uplift_commits(unified_head, commits)

    return False


def _submit(repo: Repository, args: argparse.Namespace):
    telemetry().submission.preparation_time.start()
    with wait_message("Checking connection to Phabricator."):
        # Check if raw Conduit API can be used
        if not conduit.check():
            raise Error("Failed to use Conduit API")

        # Check if local and remote VCS matches
        repo.check_vcs()

    repo.before_submit()

    # Find and preview commits to submits.
    with wait_message("Looking for commits.."):
        commits = repo.commit_stack(single=args.single)
    if not commits:
        raise Error("Failed to find any commits to submit")

    if args.command == "uplift":
        # Perform uplift logic during submission.
        avoid_local_changes = local_uplift_if_possible(args, repo, commits)
    else:
        avoid_local_changes = False

    with wait_message("Loading commits.."):
        # Pre-process to load metadata.
        morph_blocking_reviewers(commits)
        augment_commits_from_body(commits)
        update_commits_from_args(commits, args)
        rev_ids = [commit.rev_id for commit in commits if commit.rev_id is not None]
        if args.command == "uplift":
            revisions = conduit.get_revisions(ids=rev_ids) if rev_ids else []
            revisions = {revision["id"]: revision for revision in revisions}
            update_commits_for_uplift(commits, revisions, repo)
        update_commit_title_previews(commits)

    # Display a one-line summary of commit and WIP count.
    commit_count = len(commits)
    wip_commit_count = sum(1 for commit in commits if commit.wip)

    if wip_commit_count == commit_count:
        status = "as Work In Progress"
    elif wip_commit_count:
        status = f"{wip_commit_count} as Work In Progress"
    else:
        status = "for review"

    logger.warning(f"Submitting {commit_count} commit{'s'[:commit_count^1]} {status}")

    # Validate commit stack is suitable for review.
    show_commit_stack(commits, args, validate=True)
    try:
        with wait_message("Checking commits.."):
            repo.check_commits_for_submit(commits, require_bug=not args.no_bug)
    except Error as e:
        if not args.force:
            raise Error("Unable to submit commits:\n\n%s" % e)
        logger.error("Ignoring issues found with commits:\n\n%s", e)

    if not any(commit.submit for commit in commits):
        logger.warning("No changes to submit.")
        return

    # Show a warning if there are untracked files.
    if config.warn_untracked:
        untracked = repo.untracked()
        if untracked:
            logger.warning(
                "Warning: found %s untracked file%s (will not be submitted):",
                len(untracked),
                "" if len(untracked) == 1 else "s",
            )
            if len(untracked) <= 5:
                for filename in untracked:
                    logger.info("  %s", filename)

    # Show a warning if -m is used and there are new commits.
    if args.message and any(commit for commit in commits if not commit.rev_id):
        logger.warning(
            "Warning: --message works with updates only, and will not\n"
            "result in a comment on new revisions."
        )

    telemetry().submission.preparation_time.stop()
    telemetry().submission.commits_count.add(len(commits))

    # Confirmation prompt.
    if args.yes:
        pass
    elif config.auto_submit and not args.interactive:
        logger.info(
            "Automatically submitting (as per submit.auto_submit in %s)",
            config.filename,
        )
    else:
        res = prompt(
            "Submit to %s" % PHABRICATOR_URLS.get(repo.phab_url, repo.phab_url),
            ["Yes", "No", "Always"],
        )
        if res == "No":
            return
        if res == "Always":
            config.auto_submit = True
            config.write()

    # Process.
    telemetry().submission.process_time.start()
    # Collect all existing revisions to get reviewers info.
    revisions_to_update = None
    if rev_ids:
        with wait_message("Loading revision data..."):
            list_to_update = conduit.get_revisions(ids=rev_ids)

        revisions_to_update = {revision["id"]: revision for revision in list_to_update}

    previous_commit = None
    for commit in commits:
        if not commit.submit:
            previous_commit = commit
            continue

        # Only revisions being updated have an ID. Newly created ones don't.
        is_update = bool(commit.rev_id)
        revision_to_update = revisions_to_update[commit.rev_id] if is_update else None
        has_existing_reviewers = (
            bool(revision_to_update["attachments"]["reviewers"]["reviewers"])
            if revision_to_update
            else False
        )

        # Let the user know something's happening.
        if is_update:
            logger.info("\nUpdating revision D%s:", commit.rev_id)
        else:
            logger.info("\nCreating new revision:")

        logger.info("%s %s", commit.name, commit.revision_title())

        # Create a diff if needed
        with wait_message("Creating local diff..."):
            diff = repo.get_diff(commit)

        if diff:
            telemetry().submission.files_count.add(len(diff.changes))
            with wait_message("Uploading binary file(s)..."):
                conduit.upload_files_from_diff(diff)

            with wait_message("Submitting the diff..."):
                result = conduit.submit_diff(diff, commit)
                diff.phid = result["phid"]
                diff.id = result["diffid"]

        if is_update:
            with wait_message("Updating revision..."):
                rev = conduit.update_revision(
                    commit,
                    has_existing_reviewers,
                    diff_phid=diff.phid,
                    comment=args.message,
                )
        else:
            with wait_message("Creating a new revision..."):
                rev = conduit.create_revision(
                    commit,
                    diff.phid,
                    # Set the parent revision if one is available.
                    parent_rev_phid=(
                        previous_commit.rev_phid if previous_commit else None
                    ),
                )

        # Set revision ID and PHID from the Conduit API response.
        commit.rev_id = rev["object"]["id"]
        commit.rev_phid = rev["object"]["phid"]

        revision_url = "%s/D%s" % (repo.phab_url, commit.rev_id)

        # Append/replace div rev url to/in commit description.
        body = amend_revision_url(commit.body, revision_url)

        # Amend the commit if required.
        # As commit rewriting can be expensive we avoid it in some circumstances, such
        # as pre-pending "WIP: " to commits submitted as WIP to Phabricator.
        if commit.title_preview != commit.title or body != commit.body:
            commit.title = commit.title_preview
            commit.body = body

            if not avoid_local_changes:
                with wait_message("Updating commit.."):
                    repo.amend_commit(commit, commits)

        # Diff property has to be set after potential SHA1 change.
        if diff:
            with wait_message("Setting diff metadata..."):
                message = commit.build_arc_commit_message()
                conduit.set_diff_property(diff.id, commit, message)

        previous_commit = commit

    # Cleanup (eg. strip nodes) and refresh to ensure the stack is right for the
    # final showing.
    with wait_message("Cleaning up.."):
        if args.command != "uplift":
            repo.finalize(commits)
        repo.after_submit()
        repo.cleanup()
        repo.refresh_commit_stack(commits)

    logger.warning("\nCompleted")
    show_commit_stack(
        commits, args, validate=False, show_rev_urls=True, show_updated_only=True
    )
    telemetry().submission.process_time.stop()


def submit(repo: Repository, args: argparse.Namespace):
    try:
        _submit(repo, args)
    except Exception as e:
        # Check if the `fallback` flag was set and print a warning message.
        if hasattr(args, "fallback") and args.fallback:
            logger.warning(
                "You didn't specify a valid command, so we ran `submit` for you, "
                "and it failed."
            )

        raise e


def add_parser(parser):
    submit_parser = parser.add_parser(
        "submit",
        aliases=["upload"],
        help="Submit commit(s) to Phabricator.",
        description=(
            "MozPhab will change the working directory and amend the commits during "
            "the submission process."
        ),
    )
    add_submit_arguments(submit_parser)
    submit_parser.set_defaults(func=submit, needs_repo=True)


def add_submit_arguments(parser):
    """Add `moz-phab submit` command line arguments to a parser."""
    parser.add_argument(
        "--path", "-p", help="Set path to repository (default: detected)."
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Submit without confirmation (default: %s)." % config.auto_submit,
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Submit with confirmation (default: %s)." % (not config.auto_submit),
    )
    parser.add_argument(
        "--message",
        "-m",
        help="Provide a custom update message (default: none).",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Override sanity checks and force submission; a tool of last resort.",
    )
    parser.add_argument(
        "--force-delete",
        action="store_true",
        help="Mercurial only: Ignore error caused by a DAG branch point without "
        "evolve installed.",
    )
    parser.add_argument(
        "--bug",
        "-b",
        help="Set Bug ID for all commits (default: from commit).",
        type=str,
    )
    parser.add_argument(
        "--no-bug",
        action="store_true",
        help="Continue if a bug number is not provided.",
    )
    parser.add_argument(
        "--reviewer",
        "--reviewers",
        "-r",
        action="append",
        help="Set review(s) for all commits (default: from commit).",
    )
    parser.add_argument(
        "--blocker",
        "--blockers",
        "-R",
        action="append",
        help="Set blocking review(s) for all commits (default: from commit).",
    )
    parser.add_argument(
        "--nolint",
        "--no-lint",
        action="store_true",
        help="Do not run lint (default: lint changed files if configured).",
    )
    wip_group = parser.add_mutually_exclusive_group()
    wip_group.add_argument(
        "--wip",
        "--plan-changes",
        action="store_true",
        help="Create or update a revision without requesting a code review.",
    )
    wip_group.add_argument(
        "--no-wip",
        action="store_true",
        help="Don't mark reviewer-less commits as work-in-progress. Commits "
        "with descriptions that start with WIP: will continue to be "
        "flagged as work-in-progress.",
    )
    parser.add_argument(
        "--less-context",
        "--lesscontext",
        action="store_true",
        dest="lesscontext",
        help=(
            "Normally, files are diffed with full context: the entire file "
            "is sent to Phabricator so reviewers can 'show more' and see "
            "it. If you are making changes to very large files with tens of "
            "thousands of lines, this may not work well. With this flag, a "
            "revision will be created that has only a few lines of context."
        ),
    )
    parser.add_argument(
        "--no-stack",
        action="store_true",
        help="Submit multiple commits, but do not mark them as dependent.",
    )
    parser.add_argument(
        "--upstream",
        "--remote",
        "-u",
        action="append",
        help='Set upstream branch to detect the starting commit (default: "").',
    )
    parser.add_argument(
        "--force-vcs",
        action="store_true",
        help="EXPERIMENTAL: Override VCS compatibility check.",
    )
    parser.add_argument(
        "--safe-mode",
        dest="safe_mode",
        action="store_true",
        help="Run VCS with only necessary extensions.",
    )
    parser.add_argument(
        "--single",
        "-s",
        action="store_true",
        help="Submit a single commit.",
    )
    parser.add_argument(
        "start_rev",
        nargs="?",
        default=environment.DEFAULT_START_REV,
        help="Start revision of range to submit (default: detected).",
    )
    parser.add_argument(
        "end_rev",
        nargs="?",
        default=environment.DEFAULT_END_REV,
        help="End revision of range to submit (default: current commit).",
    )
