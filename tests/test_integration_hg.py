# coding=utf-8
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os
import platform
import shutil
from unittest import mock

import pytest
from callee import Contains, Matching, StartsWith

from mozphab import mozphab

from .conftest import hg_out, write_text

# Fail if arc ping is called
arc_ping = mock.Mock()
arc_ping.return_value = False

call_conduit = mock.Mock()


def test_submit_create(in_process, hg_repo_path):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        [{"userName": "alice", "phid": "PHID-USER-1"}],
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    a_rename = hg_repo_path / "A to rename"
    write_text(a_rename, "rename me\nsecond line\n")

    b_remove = hg_repo_path / "B to remove"
    write_text(b_remove, "remove me\n")

    c_modify = hg_repo_path / "C to modify"
    write_text(c_modify, "modify me\n")

    d_copy = hg_repo_path / "D to copy"
    write_text(d_copy, "copy me\n")

    hg_out("add")
    hg_out("commit", "-m", "first")

    a_rename.rename(hg_repo_path / "A renamed")
    b_remove.unlink()
    write_text(c_modify, "modified\n")
    hg_out("copy", d_copy, "D copied")

    e_subdir = hg_repo_path / "subdir"
    e_subdir.mkdir()
    write_text(e_subdir / "E add", "added\n")

    hg_out("addremove")

    msg = hg_repo_path / "msg"
    write_text(msg, "Ą r?alice", encoding="utf-8")
    hg_out("commit", "-l", msg)
    msg.unlink()

    mozphab.main(["submit", "--yes", "--bug", "1", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - Ą r?alice

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert mock.call("conduit.ping", {}) in call_conduit.call_args_list
    assert (
        mock.call("user.query", {"usernames": ["alice"]}) in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "diffusion.repository.search",
            {"limit": 1, "constraints": {"callsigns": ["TEST"]}},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "differential.setdiffproperty",
            {"diff_id": "1", "name": "local:commits", "data": Contains('"rev": "')},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "differential.creatediff",
            {
                "sourceControlPath": "/",
                "sourceControlSystem": "hg",
                "lintStatus": "none",
                "sourcePath": mock.ANY,
                "unitStatus": "none",
                "sourceMachine": "http://example.test",
                "sourceControlBaseRevision": mock.ANY,
                "repositoryPHID": "PHID-REPO-1",
                "branch": "default",
                "changes": [
                    {
                        "currentPath": "A renamed",
                        "type": 6,  # MOVE_HERE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 2,
                                "newOffset": 1,
                                "newLength": 2,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " rename me\n second line\n",
                            }
                        ],
                        "oldProperties": {},
                        "oldPath": "A to rename",
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "A to rename",
                        "type": 4,  # MOVE_AWAY
                        "hunks": [],
                        "oldProperties": {},
                        "oldPath": None,
                        "commitHash": mock.ANY,
                        "awayPaths": ["A renamed"],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "B to remove",
                        "type": 3,  # DELETE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 0,
                                "newLength": 0,
                                "addLines": 0,
                                "delLines": 1,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": "-remove me\n",
                            }
                        ],
                        "awayPaths": [],
                        "fileType": 1,
                        "oldPath": "B to remove",
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "oldProperties": {"unix:filemode": "100644"},
                    },
                    {
                        "currentPath": "C to modify",
                        "type": 2,  # CHANGE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 1,
                                "delLines": 1,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": "-modify me\n+modified\n",
                            }
                        ],
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "fileType": 1,
                        "oldPath": "C to modify",
                        "newProperties": {},
                        "awayPaths": [],
                        "oldProperties": {},
                    },
                    {
                        "metadata": {},
                        "oldPath": "D to copy",
                        "currentPath": "D copied",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 7,  # COPY HERE
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " copy me\n",
                            }
                        ],
                    },
                    {
                        "metadata": {},
                        "oldPath": None,
                        "currentPath": "D to copy",
                        "awayPaths": ["D copied"],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 5,  # COPY AWAY
                        "fileType": 1,
                        "hunks": [],
                    },
                    {
                        "currentPath": "subdir/E add",
                        "type": 1,  # ADD
                        "hunks": [
                            {
                                "corpus": "+added\n",
                                "addLines": 1,
                                "oldOffset": 0,
                                "newOffset": 1,
                                "newLength": 1,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "oldLength": 0,
                                "isMissingNewNewline": False,
                            }
                        ],
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "newProperties": {"unix:filemode": "100644"},
                        "oldPath": None,
                        "oldProperties": {},
                        "fileType": 1,
                        "metadata": {},
                    },
                ],
                "creationMethod": "moz-phab-hg",
            },
        )
        in call_conduit.call_args_list
    )
    call_conduit.assert_any_call(
        "differential.revision.edit",
        {
            "transactions": [
                {"type": "title", "value": StartsWith("Bug 1 - ")},
                {"type": "summary", "value": ""},
                {"type": "reviewers.set", "value": ["PHID-USER-1"]},
                {"type": "bugzilla.bug-id", "value": "1"},
                {"type": "update", "value": "PHID-DIFF-1"},
            ]
        },
    )


def test_submit_create_no_trailing_newline(in_process, hg_repo_path):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        [{"userName": "alice", "phid": "PHID-USER-1"}],
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    a_rename = hg_repo_path / "A to rename"
    write_text(a_rename, "rename me\nsecond line")

    b_remove = hg_repo_path / "B to remove"
    write_text(b_remove, "remove me")

    c_modify = hg_repo_path / "C to modify"
    write_text(c_modify, "modify me")

    d_copy = hg_repo_path / "D to copy"
    write_text(d_copy, "copy me")

    hg_out("add")
    hg_out("commit", "-m", "first")

    a_rename.rename(hg_repo_path / "A renamed")
    b_remove.unlink()
    write_text(c_modify, "modified")
    hg_out("copy", d_copy, "D copied")

    e_subdir = hg_repo_path / "subdir"
    e_subdir.mkdir()
    write_text(e_subdir / "E add", "added")

    hg_out("addremove")

    msg = hg_repo_path / "msg"
    write_text(msg, "Ą r?alice", encoding="utf-8")
    hg_out("commit", "-l", msg)
    msg.unlink()

    mozphab.main(["submit", "--yes", "--bug", "1", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - Ą r?alice

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert mock.call("conduit.ping", {}) in call_conduit.call_args_list
    assert (
        mock.call("user.query", {"usernames": ["alice"]}) in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "diffusion.repository.search",
            {"limit": 1, "constraints": {"callsigns": ["TEST"]}},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "differential.setdiffproperty",
            {"diff_id": "1", "name": "local:commits", "data": Contains('"rev": "')},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "differential.creatediff",
            {
                "sourceControlPath": "/",
                "sourceControlSystem": "hg",
                "lintStatus": "none",
                "sourcePath": mock.ANY,
                "unitStatus": "none",
                "sourceMachine": "http://example.test",
                "sourceControlBaseRevision": mock.ANY,
                "repositoryPHID": "PHID-REPO-1",
                "branch": "default",
                "changes": [
                    {
                        "currentPath": "A renamed",
                        "type": 6,  # MOVE_HERE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 2,
                                "newOffset": 1,
                                "newLength": 2,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " rename me\n second line",
                            }
                        ],
                        "oldProperties": {},
                        "oldPath": "A to rename",
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "A to rename",
                        "type": 4,  # MOVE_AWAY
                        "hunks": [],
                        "oldProperties": {},
                        "oldPath": None,
                        "commitHash": mock.ANY,
                        "awayPaths": ["A renamed"],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "B to remove",
                        "type": 3,  # DELETE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 2,
                                "newOffset": 0,
                                "newLength": 0,
                                "addLines": 0,
                                "delLines": 1,
                                "isMissingOldNewline": True,
                                "isMissingNewNewline": False,
                                "corpus": "-remove me\n\\ No newline at end of file\n",
                            }
                        ],
                        "awayPaths": [],
                        "fileType": 1,
                        "oldPath": "B to remove",
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "oldProperties": {"unix:filemode": "100644"},
                    },
                    {
                        "currentPath": "C to modify",
                        "type": 2,  # CHANGE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 1,
                                "delLines": 1,
                                "isMissingOldNewline": True,
                                "isMissingNewNewline": True,
                                "corpus": (
                                    "-modify me\n"
                                    "\\ No newline at end of file\n"
                                    "+modified\n"
                                    "\\ No newline at end of file\n"
                                ),
                            }
                        ],
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "fileType": 1,
                        "oldPath": "C to modify",
                        "newProperties": {},
                        "awayPaths": [],
                        "oldProperties": {},
                    },
                    {
                        "metadata": {},
                        "oldPath": "D to copy",
                        "currentPath": "D copied",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 7,  # COPY HERE
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " copy me",
                            }
                        ],
                    },
                    {
                        "metadata": {},
                        "oldPath": None,
                        "currentPath": "D to copy",
                        "awayPaths": ["D copied"],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 5,  # COPY AWAY
                        "fileType": 1,
                        "hunks": [],
                    },
                    {
                        "currentPath": "subdir/E add",
                        "type": 1,  # ADD
                        "hunks": [
                            {
                                "oldOffset": 0,
                                "oldLength": 0,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 1,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": True,
                                "corpus": "+added\n\\ No newline at end of file\n",
                            }
                        ],
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "newProperties": {"unix:filemode": "100644"},
                        "oldPath": None,
                        "oldProperties": {},
                        "fileType": 1,
                        "metadata": {},
                    },
                ],
                "creationMethod": "moz-phab-hg",
            },
        )
        in call_conduit.call_args_list
    )


def test_submit_create_no_bug(in_process, hg_repo_path):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        [{"userName": "alice", "phid": "PHID-USER-1"}],
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    write_text(hg_repo_path / "x", "a")
    hg_out("add")
    hg_out("commit", "--message", "A r?alice")
    mozphab.main(["submit", "--yes", "--no-bug", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
A r?alice

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()


def test_submit_create_binary(in_process, hg_repo_path, data_file):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # file.allocate
        {"filePHID": None, "upload": True},
        # file.upload
        {},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    shutil.copyfile(str(data_file), str(hg_repo_path / "img.png"))
    hg_out("add")
    hg_out("commit", "-m", "IMG")

    mozphab.main(["submit", "--yes", "--bug", "1", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - IMG

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "file.allocate",
            {"name": "img.png", "contentHash": mock.ANY, "contentLength": 182},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call("file.upload", {"data_base64": mock.ANY, "name": "img.png"})
        in call_conduit.call_args_list
    )


def test_submit_create_binary_existing(in_process, hg_repo_path, data_file):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # file.allocate
        {"filePHID": "PHID-FILE-1", "upload": False},
        # no file.upload call
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    shutil.copyfile(str(data_file), str(hg_repo_path / "img.png"))
    hg_out("add")
    hg_out("commit", "-m", "IMG")

    mozphab.main(["submit", "--yes", "--bug", "1", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - IMG

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "file.allocate",
            {"name": "img.png", "contentHash": mock.ANY, "contentLength": 182},
        )
        in call_conduit.call_args_list
    )
    assert mock.call("file.upload", mock.ANY) not in call_conduit.call_args_list


def test_submit_create_binary_chunked(in_process, hg_repo_path, data_file):
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # file.allocate
        {"filePHID": "PHID-FILE-1", "upload": True},
        # file.querychunks
        [
            {"byteStart": "0", "byteEnd": "4194304", "complete": False},
            {"byteStart": "4194304", "byteEnd": "8388608", "complete": False},
            {"byteStart": "8388608", "byteEnd": "8425160", "complete": False},
        ],
        # file.uploadchunk
        {},
        # file.uploadchunk
        {},
        # file.uploadchunk
        {},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    shutil.copyfile(str(data_file), str(hg_repo_path / "img.png"))
    hg_out("add")
    hg_out("commit", "-m", "IMG")

    mozphab.main(["submit", "--yes", "--bug", "1", "."], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - IMG

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "file.allocate",
            {"name": "img.png", "contentHash": mock.ANY, "contentLength": 182},
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call("file.querychunks", {"filePHID": "PHID-FILE-1"})
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "file.uploadchunk",
            {
                "filePHID": "PHID-FILE-1",
                "byteStart": 0,
                "data": mock.ANY,
                "dataEncoding": "base64",
            },
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "file.uploadchunk",
            {
                "filePHID": "PHID-FILE-1",
                "byteStart": 4194304,
                "data": mock.ANY,
                "dataEncoding": "base64",
            },
        )
        in call_conduit.call_args_list
    )
    assert (
        mock.call(
            "file.uploadchunk",
            {
                "filePHID": "PHID-FILE-1",
                "byteStart": 8388608,
                "data": mock.ANY,
                "dataEncoding": "base64",
            },
        )
        in call_conduit.call_args_list
    )


def test_submit_create_no_checkout(in_process, hg_repo_path):
    """Test that diffing behaviour is consistent even without an explicit
    checkout prior to generating diffs.

    This is a counterpart to test_integration_git.test_submit_create_no_checkout
    and is named the same for ease of localisation. It doesn't however, test
    that the Hg logic doesn't do checkouts during submissions. Currently, it
    very much does, and diffs for files touched by multiple commits end up
    containing, incorrectly, all the changes up to the tip of the branche (see
    bug 1926924).
    """
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        [{"userName": "alice", "phid": "PHID-USER-1"}],
        # First diff
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
        # Second diff
        # differential.creatediff
        {"phid": "PHID-DIFF-2", "diffid": "2"},
        # differential.revision.edit
        {"object": {"id": "124", "phid": "PHID-DREV-124"}},
        # differential.setdiffproperty
        {},
    )
    a_rename = hg_repo_path / "A to rename"
    write_text(a_rename, "rename me\nsecond line\n")

    b_remove = hg_repo_path / "B to remove"
    write_text(b_remove, "remove me\n")

    c_modify = hg_repo_path / "C to modify"
    write_text(c_modify, "modify me\n")

    d_copy = hg_repo_path / "D to copy"
    write_text(d_copy, "copy me\n")

    hg_out("add")
    hg_out("commit", "-m", "first")

    a_rename.rename(hg_repo_path / "A renamed")
    b_remove.unlink()
    write_text(c_modify, "modified\n")
    hg_out("copy", d_copy, "D copied")

    e_subdir = hg_repo_path / "subdir"
    e_subdir.mkdir()
    write_text(e_subdir / "E add", "added\n")

    hg_out("addremove")

    msg = hg_repo_path / "msg"
    write_text(msg, "Ą r?alice", encoding="utf-8")
    hg_out("commit", "-l", msg)
    msg.unlink()

    write_text(c_modify, "leave me alone\n")
    hg_out("add")
    hg_out("commit", "-m", "second")

    mozphab.main(["submit", "--yes", "--bug", "1", "-2"], is_development=True)

    expected_calls = [
        (
            "differential.creatediff",
            {
                "sourceControlPath": "/",
                "sourceControlSystem": "hg",
                "lintStatus": "none",
                "sourcePath": mock.ANY,
                "unitStatus": "none",
                "sourceMachine": "http://example.test",
                "sourceControlBaseRevision": mock.ANY,
                "repositoryPHID": "PHID-REPO-1",
                "branch": "default",
                "changes": [
                    {
                        "currentPath": "A renamed",
                        "type": 6,  # MOVE_HERE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 2,
                                "newOffset": 1,
                                "newLength": 2,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " rename me\n second line\n",
                            }
                        ],
                        "oldProperties": {},
                        "oldPath": "A to rename",
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "A to rename",
                        "type": 4,  # MOVE_AWAY
                        "hunks": [],
                        "oldProperties": {},
                        "oldPath": None,
                        "commitHash": mock.ANY,
                        "awayPaths": ["A renamed"],
                        "metadata": {},
                        "newProperties": {},
                        "fileType": 1,
                    },
                    {
                        "currentPath": "B to remove",
                        "type": 3,  # DELETE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 0,
                                "newLength": 0,
                                "addLines": 0,
                                "delLines": 1,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": "-remove me\n",
                            }
                        ],
                        "awayPaths": [],
                        "fileType": 1,
                        "oldPath": "B to remove",
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "oldProperties": {"unix:filemode": "100644"},
                    },
                    {
                        "currentPath": "C to modify",
                        "type": 2,  # CHANGE
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 1,
                                "delLines": 1,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": "-modify me\n+modified\n",
                            }
                        ],
                        "commitHash": mock.ANY,
                        "metadata": {},
                        "fileType": 1,
                        "oldPath": "C to modify",
                        "newProperties": {},
                        "awayPaths": [],
                        "oldProperties": {},
                    },
                    {
                        "metadata": {},
                        "oldPath": "D to copy",
                        "currentPath": "D copied",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 7,  # COPY HERE
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " copy me\n",
                            }
                        ],
                    },
                    {
                        "metadata": {},
                        "oldPath": None,
                        "currentPath": "D to copy",
                        "awayPaths": ["D copied"],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 5,  # COPY AWAY
                        "fileType": 1,
                        "hunks": [],
                    },
                    {
                        "currentPath": "subdir/E add",
                        "type": 1,  # ADD
                        "hunks": [
                            {
                                "corpus": "+added\n",
                                "addLines": 1,
                                "oldOffset": 0,
                                "newOffset": 1,
                                "newLength": 1,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "oldLength": 0,
                                "isMissingNewNewline": False,
                            }
                        ],
                        "commitHash": mock.ANY,
                        "awayPaths": [],
                        "newProperties": {"unix:filemode": "100644"},
                        "oldPath": None,
                        "oldProperties": {},
                        "fileType": 1,
                        "metadata": {},
                    },
                ],
                "creationMethod": "moz-phab-hg",
            },
        ),
        (
            "differential.creatediff",
            {
                "changes": [
                    {
                        "metadata": {},
                        "oldPath": "C to modify",
                        "currentPath": "C to modify",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 2,
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 1,
                                "delLines": 1,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": "-modified\n+leave me alone\n",
                            }
                        ],
                    }
                ],
                "sourceMachine": "http://example.test",
                "sourceControlSystem": "hg",
                "sourceControlPath": "/",
                "sourceControlBaseRevision": mock.ANY,
                "creationMethod": "moz-phab-hg",
                "lintStatus": "none",
                "unitStatus": "none",
                "repositoryPHID": "PHID-REPO-1",
                "sourcePath": mock.ANY,
                "branch": "default",
            },
        ),
    ]

    # Match expectations to the specific call to compare them to.
    # This makes failure reporting more helpful for debugging.
    matched_calls = list(
        zip(
            expected_calls,
            [
                c[0]
                for c in call_conduit.call_args_list
                if c[0][0] == "differential.creatediff"
            ],
        )
    )
    # Make sure we've got something to assert!
    assert matched_calls, "There are no differential.creatediff calls to compare!"
    for expected, actual in matched_calls:
        assert actual == expected


def test_submit_remove_cr(in_process, hg_repo_path):
    call_conduit.reset_mock()
    call_conduit.side_effect = [
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # user.search
        [{"userName": "alice", "phid": "PHID-USER-1"}],
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    ]
    test_a = hg_repo_path / "X"
    with open(test_a, "w", newline="") as f:
        f.write("a\r\nb\n")
    hg_out("add", "X")
    hg_out("commit", "--message", "A r?alice")
    # removing CR, leaving LF
    with open(test_a, "w", newline="") as f:
        f.write("a\nb\n")
    hg_out("commit", "--message", "B r?alice")

    mozphab.main(["submit", "--yes", "--bug", "1", "-s"], is_development=True)

    call_conduit.assert_any_call(
        "differential.creatediff",
        Matching(lambda x: x["changes"][0]["hunks"][0]["corpus"] == "-a\r\n+a\n b\n"),
    )


def test_submit_single_first(in_process, hg_repo_path, hg_sha):
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    write_text(hg_repo_path / "X", "a\n")
    hg_out("add", "X")
    hg_out("commit", "-m", "A")
    sha = hg_sha()
    write_text(hg_repo_path / "X", "b\n")
    hg_out("commit", "-m", "B")

    mozphab.main(
        ["submit", "--yes", "--bug", "1", "--single", sha], is_development=True
    )

    log = hg_out("log", "--template", r"{desc}\n---\n", "--limit", "2")
    expected = """\
B
---
Bug 1 - A

Differential Revision: http://example.test/D123
---
"""
    assert log == expected


def test_submit_single_last(in_process, hg_repo_path):
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    write_text(hg_repo_path / "X", "a\n")
    hg_out("add", "X")
    hg_out("commit", "-m", "A")
    write_text(hg_repo_path / "X", "b\n")
    hg_out("commit", "-m", "B")

    mozphab.main(["submit", "--yes", "--bug", "1", "--single"], is_development=True)

    log = hg_out("log", "--template", r"{desc}\n---\n", "--limit", "2")
    expected = """\
Bug 1 - B

Differential Revision: http://example.test/D123
---
A
---
"""
    assert log == expected


def test_multiple_copy(in_process, hg_repo_path):
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    write_text(hg_repo_path / "X", "a\n")
    hg_out("add", "X")
    hg_out("commit", "-m", "A")
    hg_out("cp", "X", "X_copy_1")
    hg_out("cp", "X", "X_copy_2")
    hg_out("commit", "-m", "multiple copy")

    mozphab.main(["submit", "--yes", "--bug", "1", "--single"], is_development=True)

    assert (
        mock.call(
            "differential.creatediff",
            {
                "changes": [
                    {
                        "metadata": {},
                        "oldPath": None,
                        "currentPath": "X",
                        "awayPaths": ["X_copy_1", "X_copy_2"],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 5,  # COPY_AWAY
                        "fileType": 1,
                        "hunks": [],
                    },
                    {
                        "metadata": {},
                        "oldPath": "X",
                        "currentPath": "X_copy_1",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 7,
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " a\n",
                            }
                        ],
                    },
                    {
                        "metadata": {},
                        "oldPath": "X",
                        "currentPath": "X_copy_2",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 7,
                        "fileType": 1,
                        "hunks": [
                            {
                                "oldOffset": 1,
                                "oldLength": 1,
                                "newOffset": 1,
                                "newLength": 1,
                                "addLines": 0,
                                "delLines": 0,
                                "isMissingOldNewline": False,
                                "isMissingNewNewline": False,
                                "corpus": " a\n",
                            }
                        ],
                    },
                ],
                "sourceMachine": "http://example.test",
                "sourceControlSystem": "hg",
                "sourceControlPath": "/",
                "sourceControlBaseRevision": mock.ANY,
                "creationMethod": "moz-phab-hg",
                "lintStatus": "none",
                "unitStatus": "none",
                "repositoryPHID": "PHID-REPO-1",
                "sourcePath": mock.ANY,
                "branch": "default",
            },
        )
        in call_conduit.call_args_list
    )


# To re-enable this test for Windows we would need a way to modify
# UMASK bits similar to how it's done in test_integration_git.py.
# However, Mercurial doesn't have an equivalent to `git update-index`.
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Skipped because Windows cannot modify UMASK bits",
)
def test_empty_file(in_process, hg_repo_path, hg_sha):
    # Add empty file
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # ping
        {},
        # diffusion.repository.search
        {"data": [{"phid": "PHID-REPO-1", "fields": {"vcs": "hg"}}]},
        # differential.creatediff
        {"phid": "PHID-DIFF-1", "diffid": "1"},
        # differential.revision.edit
        {"object": {"id": "123", "phid": "PHID-DREV-123"}},
        # differential.setdiffproperty
        {},
    )
    testfile = hg_repo_path / "X"
    testfile.touch()
    hg_out("add")
    hg_out("commit", "-m", "A")
    sha = hg_sha()
    mozphab.main(["submit", "--yes", "--bug", "1", sha], is_development=True)
    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - A

Differential Revision: http://example.test/D123
"""
    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "differential.creatediff",
            {
                "changes": [
                    {
                        "metadata": {},
                        "oldPath": None,
                        "currentPath": "X",
                        "awayPaths": [],
                        "oldProperties": {},
                        "newProperties": {"unix:filemode": "100644"},
                        "commitHash": mock.ANY,
                        "type": 1,
                        "fileType": 1,
                        "hunks": [],
                    }
                ],
                "sourceMachine": "http://example.test",
                "sourceControlSystem": "hg",
                "sourceControlPath": "/",
                "sourceControlBaseRevision": mock.ANY,
                "creationMethod": "moz-phab-hg",
                "lintStatus": "none",
                "unitStatus": "none",
                "repositoryPHID": "PHID-REPO-1",
                "sourcePath": mock.ANY,
                "branch": "default",
            },
        )
        in call_conduit.call_args_list
    ), (
        "The diff should have populated fields and "
        "`change.hunks` should be an empty list"
    )

    # Modify a file's mode
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # differential.creatediff
        {"phid": "PHID-DIFF-2", "diffid": "2"},
        # differential.revision.edit
        {"object": {"id": "124", "phid": "PHID-DREV-124"}},
        # differential.setdiffproperty
        {},
    )
    os.chmod(testfile, 0o0755)

    hg_out("commit", "-m", "B")
    sha = hg_sha()
    mozphab.main(["submit", "--yes", "--bug", "1", sha], is_development=True)
    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - B

Differential Revision: http://example.test/D124
"""
    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "differential.creatediff",
            {
                "changes": [
                    {
                        "metadata": {},
                        "oldPath": "X",
                        "currentPath": "X",
                        "awayPaths": [],
                        "oldProperties": {"unix:filemode": "100644"},
                        "newProperties": {"unix:filemode": "100755"},
                        "commitHash": mock.ANY,
                        "type": 2,
                        "fileType": 1,
                        "hunks": [],
                    }
                ],
                "sourceMachine": "http://example.test",
                "sourceControlSystem": "hg",
                "sourceControlPath": "/",
                "sourceControlBaseRevision": mock.ANY,
                "creationMethod": "moz-phab-hg",
                "lintStatus": "none",
                "unitStatus": "none",
                "repositoryPHID": "PHID-REPO-1",
                "sourcePath": mock.ANY,
                "branch": "default",
            },
        )
        in call_conduit.call_args_list
    ), (
        "The diff should contain filemode changes and "
        "`change.hunks` should be an empty list"
    )

    # Remove an empty file
    call_conduit.reset_mock()
    call_conduit.side_effect = (
        # differential.creatediff
        {"phid": "PHID-DIFF-3", "diffid": "3"},
        # differential.revision.edit
        {"object": {"id": "125", "phid": "PHID-DREV-125"}},
        # differential.setdiffproperty
        {},
    )
    testfile.unlink()
    hg_out("addremove")
    hg_out("commit", "-m", "C")
    sha = hg_sha()
    mozphab.main(["submit", "--yes", "--bug", "1", sha], is_development=True)
    log = hg_out("log", "--template", r"{desc}\n", "--rev", ".")
    expected = """
Bug 1 - C

Differential Revision: http://example.test/D125
"""

    assert log.strip() == expected.strip()
    assert (
        mock.call(
            "differential.creatediff",
            {
                "changes": [
                    {
                        "metadata": {},
                        "oldPath": "X",
                        "currentPath": "X",
                        "awayPaths": [],
                        "oldProperties": {"unix:filemode": "100755"},
                        "newProperties": {},
                        "commitHash": mock.ANY,
                        "type": 3,
                        "fileType": 1,
                        "hunks": [],
                    }
                ],
                "sourceMachine": "http://example.test",
                "sourceControlSystem": "hg",
                "sourceControlPath": "/",
                "sourceControlBaseRevision": mock.ANY,
                "creationMethod": "moz-phab-hg",
                "lintStatus": "none",
                "unitStatus": "none",
                "repositoryPHID": "PHID-REPO-1",
                "sourcePath": mock.ANY,
                "branch": "default",
            },
        )
        in call_conduit.call_args_list
    ), (
        "The diff should have empty `newProperties` and "
        "`change.hunks` should be an empty list"
    )
