#!/usr/bin/env python

# Copyright 2016 Red Hat, Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function
import argparse
import os
import platform
import re
import subprocess
import sys


__metaclass__ = type
TITLE_RE = re.compile("\\[(.*)\\]")
NAME_RE = re.compile("name=(.+)")
PRIORITY_RE = re.compile("priority=\\d+")
DEFAULT_OUTPUT_PATH = "/etc/yum.repos.d"
DEFAULT_RDO_MIRROR = "https://trunk.rdoproject.org"

# RHEL is only provided to licensed cloud providers via RHUI
DEFAULT_MIRROR_MAP = {
    "centos8": "http://mirror.centos.org",
    "centos9": "http://mirror.stream.centos.org",
    "centos10": "http://mirror.stream.centos.org",
    "ubi8": "http://mirror.centos.org",
    "ubi9": "http://mirror.stream.centos.org",
    "rhel8": "https://trunk.rdoproject.org",
    "rhel9": "https://trunk.rdoproject.org",
}
CEPH_REPO_TEMPLATE = """
[repo-setup-centos-ceph-%(ceph_release)s]
name=repo-setup-centos-ceph-%(ceph_release)s
baseurl=%(mirror)s/centos/%(centos_release)s/storage/$basearch/ceph-%(ceph_release)s/
gpgcheck=0
enabled=1
"""
CEPH_SIG_REPO_TEMPLATE = """
[repo-setup-centos-ceph-%(ceph_release)s]
name=repo-setup-centos-ceph-%(ceph_release)s
baseurl=%(mirror)s/SIGs/%(centos_release)s/storage/$basearch/ceph-%(ceph_release)s/
gpgcheck=0
enabled=1
"""
CEPH_RDO_REPO_TEMPLATE = """
[repo-setup-centos-ceph-%(ceph_release)s]
name=repo-setup-centos-ceph-%(ceph_release)s
baseurl=https://trunk.rdoproject.org/centos8-master/deps/storage/%(ceph_release)s/
gpgcheck=0
enabled=1
"""
# centos-8 only
HIGHAVAILABILITY_REPO_TEMPLATE = """
[repo-setup-centos-highavailability]
name=repo-setup-centos-highavailability
baseurl=%(mirror)s/%(legacy_url)s%(stream)s/HighAvailability/$basearch/os/
gpgcheck=0
enabled=1
"""
# centos-8 only
POWERTOOLS_REPO_TEMPLATE = """
[repo-setup-centos-powertools]
name=repo-setup-centos-powertools
baseurl=%(mirror)s/%(legacy_url)s%(stream)s/%(pt_name)s/$basearch/os/
gpgcheck=0
enabled=1
"""
# ubi-8 only
APPSTREAM_REPO_TEMPLATE = """
[repo-setup-centos-appstream]
name=repo-setup-centos-appstream
baseurl=%(mirror)s/%(legacy_url)s%(stream)s/AppStream/$basearch/os/
gpgcheck=0
enabled=1
%(extra)s
"""
BASE_REPO_TEMPLATE = """
[repo-setup-centos-baseos]
name=repo-setup-centos-baseos
baseurl=%(mirror)s/%(legacy_url)s%(stream)s/BaseOS/$basearch/os/
gpgcheck=0
enabled=1
"""


# unversioned fedora added for backwards compatibility
SUPPORTED_DISTROS = [
    ("centos", "8"),
    ("centos", "9"),
    ("centos", "10"),
    ("rhel", "8"),
    ("rhel", "9"),
    ("ubi", "8"),
    ("ubi", "9"),  # a subcase of the rhel distro
]
DISTRO_CHOICES = ["".join(distro_pair) for distro_pair in SUPPORTED_DISTROS]


class InvalidArguments(Exception):
    pass


class NoRepoTitle(Exception):
    pass


def _get_distro():
    """Get distro info from os-release

    returns: distro_id, distro_major_version_id, distro_name
    """
    # Avoids a crash on unsupported platforms which would prevent even
    # running with `--help`.
    if not os.path.exists("/etc/os-release"):
        return platform.system(), "unknown", "unknown"

    output = subprocess.Popen(
        'source /etc/os-release && echo -e -n "$ID\n$VERSION_ID\n$NAME"',
        shell=True,
        stdout=subprocess.PIPE,
        stderr=open(os.devnull, "w"),
        executable="/bin/bash",
        universal_newlines=True,
    ).communicate()

    # distro_id and distro_version_id will always be at least an empty string
    distro_id, distro_version_id, distro_name = output[0].split("\n")

    # if distro_version_id is empty string the major version will be empty
    # string too
    distro_major_version_id = distro_version_id.split(".")[0]

    # check if that is UBI subcase?
    if os.path.exists("/etc/yum.repos.d/ubi.repo"):
        distro_id = "ubi"

    if (distro_id, distro_major_version_id) not in SUPPORTED_DISTROS:
        print(
            "WARNING: Unsupported platform '{0}{1}' detected by repo-setup,"
            " centos9 will be used unless you use CLI param to change it."
            "".format(distro_id, distro_major_version_id),
            file=sys.stderr,
        )
        distro_id = "centos"
        distro_major_version_id = "9"

    if distro_id == "ubi":
        print(
            "WARNING: Centos{0} Base and AppStream will be installed for "
            "this UBI distro".format(distro_major_version_id)
        )

    return distro_id, distro_major_version_id, distro_name


def _parse_args(distro_id, distro_major_version_id):
    distro = "{0}{1}".format(distro_id, distro_major_version_id)

    parser = argparse.ArgumentParser(
        description="Download and install repos necessary for OpenStack. Note "
        "that some of these repos require yum-plugin-priorities, "
        "so that will also be installed.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "repos",
        metavar="REPO",
        nargs="+",
        choices=[
            "current",
            "consistent",
            "deps",
            "current-podified",
            "current-podified-dev",
            "ceph",
            "podified-ci-testing",
            "current-podified-rdo",
        ],
        help="A list of repos.  Available repos: "
        "%(choices)s.  The deps repo will always be "
        "included when using current or "
        "current-podified.  current-podified-dev "
        "downloads the current-podified, current, and "
        "deps repos, but sets the current repo to only "
        "be used for OpenStack projects. It also modifies "
        "each repo's priority so packages are installed "
        "from the appropriate location.",
    )
    parser.add_argument(
        "-d",
        "--distro",
        default=distro,
        choices=DISTRO_CHOICES,
        nargs="?",
        help="Target distro with default detected at runtime. ",
    )
    parser.add_argument(
        "-b",
        "--branch",
        default="master",
        help="Target branch. Should be the lowercase name of "
        "the OpenStack release. e.g. liberty",
    )
    parser.add_argument(
        "-o",
        "--output-path",
        default=DEFAULT_OUTPUT_PATH,
        help="Directory in which to save the selected repos.",
    )
    parser.add_argument(
        "--mirror",
        help="Server from which to install base OS packages. "
        "Default value is based on distro param.",
    )
    parser.add_argument(
        "--rdo-mirror",
        default=DEFAULT_RDO_MIRROR,
        help="Server from which to install RDO packages.",
    )
    parser.add_argument(
        "--dlrn-hash-tag",
        help="Generate DLRN repos using specific dlrn tag",
    )
    stream_group = parser.add_mutually_exclusive_group()
    stream_group.add_argument(
        "--stream",
        action="store_true",
        default=True,
        help="Enable stream support for CentOS repos",
    )
    stream_group.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        help="Disable stream support for CentOS repos",
    )

    args = parser.parse_args()
    if args.no_stream:
        args.stream = False

    # Default mirror for args.distro (which defaults to 'distro')
    default_mirror = DEFAULT_MIRROR_MAP.get(args.distro, None)

    if args.mirror is None:
        args.mirror = default_mirror
    args.old_mirror = default_mirror

    return args


def _get_repo(path, args):
    # lazy import
    if "requests" not in globals():
        import requests

    r = requests.get(path)
    if r.status_code == 200:
        return _inject_mirrors(r.text, args)
    else:
        r.raise_for_status()


def _write_repo(content, target, name=None):
    if not name:
        m = TITLE_RE.search(content)
        if not m:
            raise NoRepoTitle("Could not find repo title in: \n%s" % content)
        name = m.group(1)
        # centos-8 dlrn repos have changed. repos per component
        # are folded into a single repo.
        if "component" in name:
            name = "delorean"
    filename = name + ".repo"
    filename = os.path.join(target, filename)
    with open(filename, "w") as f:
        f.write(content)
    print("Installed repo %s to %s" % (name, filename))


def _validate_distro_repos(args):
    """Validate requested repos are valid for the distro"""
    valid_repos = []
    if "fedora" in args.distro:
        valid_repos = [
            "current",
            "consistent",
            "current-podified",
            "ceph",
            "deps",
            "podified-ci-testing",
        ]
    elif args.distro in DISTRO_CHOICES:
        valid_repos = [
            "ceph",
            "current",
            "consistent",
            "current-podified",
            "deps",
            "podified-ci-testing",
        ]
    invalid_repos = [x for x in args.repos if x not in valid_repos]
    if len(invalid_repos) > 0:
        raise InvalidArguments(
            "{0} repo(s) are not valid for {1}. Valid repos "
            "are: {2}".format(invalid_repos, args.distro, valid_repos)
        )
    return True


def _validate_current_repos(repos):
    """Validate current usage

    current and current-podified cannot be specified with each other and
    current-podified-dev is a mix of current, current-podified and deps
    so they should not be specified on the command line with each other.
    """
    if "current-podified" in repos and "current" in repos:
        raise InvalidArguments(
            "Cannot use current and current-podified at the " "same time."
        )
    if "current-podified-dev" not in repos:
        return True
    if "current" in repos or "current-podified" in repos or "deps" in repos:
        raise InvalidArguments(
            "current-podified-dev should not be used with "
            "any other RDO Trunk repos."
        )
    return True


def _validate_podified_ci_testing(repos):
    """Validate podified-ci-testing

    With podified-ci-testing for repo (currently only periodic container build)
    no other repos expected except optionally deps|ceph|opstools
    which is enabled regardless.
    """
    if "podified-ci-testing" in repos and len(repos) > 1:
        if "deps" in repos or "ceph" in repos:
            return True
        else:
            raise InvalidArguments(
                "Cannot use podified-ci-testing at the "
                "same time as other repos, except "
                "deps|ceph."
            )
    return True


def _validate_distro_stream(args, distro_name, distro_major_version_id):
    """Validate stream related args vs host

    Fails if stream is to be used but the host isn't a stream OS or vice versa
    """
    if args.output_path != DEFAULT_OUTPUT_PATH:
        # don't validate distro name because the output path is not
        # /etc/yum.repos.d, so the repo files may not be used to install
        # packages on this host
        return True
    if "centos" not in distro_name.lower():
        return True
    if distro_name.lower() == "centos" and distro_major_version_id != "8":
        return True
    is_stream = args.stream and not args.no_stream
    if is_stream and "stream" not in distro_name.lower():
        raise InvalidArguments(
            "--stream provided, but OS is not the Stream "
            "version. Please ensure the host is Stream."
        )
    elif not is_stream and "stream" in distro_name.lower():
        raise InvalidArguments(
            "--no-stream provided, but OS is the Stream "
            "version. Please ensure the host is not the "
            "Stream version."
        )
    return True


def _validate_args(args, distro_name, distro_major_version_id):
    _validate_current_repos(args.repos)
    _validate_distro_repos(args)
    _validate_podified_ci_testing(args.repos)
    _validate_distro_stream(args, distro_name, distro_major_version_id)


def _remove_existing(args):
    """Remove any delorean* or opstools repos that already exist"""
    if args.distro in ["ubi8", "ubi9"]:
        regex = (
            "^(BaseOS|AppStream|delorean|repo-setup-centos-"
            "(ceph|highavailability|powertools)).*.repo"
        )
    else:
        regex = (
            "^(delorean|repo-setup-centos-"
            "(ceph|highavailability|powertools)).*.repo"
        )
    pattern = re.compile(regex)
    if os.path.exists("/etc/distro.repos.d"):
        paths = set(os.listdir(args.output_path) + os.listdir("/etc/distro.repos.d"))
    else:
        paths = os.listdir(args.output_path)
    for f in paths:
        if pattern.match(f):
            filename = os.path.join(args.output_path, f)
            if os.path.exists(filename):
                os.remove(filename)
                print('Removed old repo "%s"' % filename)
            filename = os.path.join("/etc/distro.repos.d", f)
            if os.path.exists(filename):
                os.remove(filename)
                print('Removed old repo "%s"' % filename)


def _get_base_path(args):
    if args.distro in ["ubi8", "ubi9"]:
        # there are no base paths for UBI that work well
        distro = args.distro.replace("ubi", "centos")
    else:
        distro = args.distro

    # The mirror url with /$DISTRO$VERSION path for master branch is
    # deprecated.
    # The default for rdo mirrors is $DISTRO$VERSION-$BRANCH
    # it should work for every (distro, branch) pair that
    # makes sense
    # Any exception should be corrected at source, not here.
    distro_branch = "%s-%s" % (distro, args.branch)
    return "%s/%s/" % (args.rdo_mirror, distro_branch)


def _create_ceph(args, release):
    """Generate a Ceph repo file for release"""
    centos_release = "9-stream"
    template = CEPH_SIG_REPO_TEMPLATE
    if args.distro == "centos8" and release == "nautilus":
        template = CEPH_RDO_REPO_TEMPLATE
    elif args.distro == "centos8":
        centos_release = "8-stream"
        template = CEPH_REPO_TEMPLATE

    return template % {
        "centos_release": centos_release,
        "ceph_release": release,
        "mirror": args.mirror,
    }


def _change_priority(content, new_priority):
    new_content = PRIORITY_RE.sub("priority=%d" % new_priority, content)
    # This shouldn't happen, but let's be safe.
    if not PRIORITY_RE.search(new_content):
        new_content = []
        for line in content.split("\n"):
            new_content.append(line)
            if line.startswith("["):
                new_content.append("priority=%d" % new_priority)
        new_content = "\n".join(new_content)
    return new_content


def _inject_mirrors(content, args):
    """Replace any references to the default mirrors in repo content

    In some cases we want to use mirrors whose repo files still point to the
    default servers.  If the user specified to use the mirror, we want to
    replace any such references with the mirror address.  This function
    handles that by using a regex to swap out the baseurl server.
    """

    content = re.sub(
        "baseurl=%s" % DEFAULT_RDO_MIRROR, "baseurl=%s" % args.rdo_mirror, content
    )

    if args.old_mirror:
        content = re.sub(
            "baseurl=%s" % args.old_mirror, "baseurl=%s" % args.mirror, content
        )

    return content


def _get_rhel_trunk_candidate_repos(args, base_path):
    content = _get_repo(base_path + "osptrunk-deps.repo", args)
    # Replace deps with candidate
    content = content.replace('deps', 'candidate')
    content = content.replace('build', 'candidate')
    content = _change_priority(content, 30)
    # Remove module_hotfixes
    content = content.split()
    content.remove('module_hotfixes=1')
    content = '\n'.join(content)
    return content


def _get_dlrn_hash_tag(args, repo):
    if args.dlrn_hash_tag:
        # If repo name is current/delorean.repo and
        # dlrn_hash_tag is b6e71147e9ec7234501c50f94860c58d
        # then returned repo value would be
        # current/b6/e7/b6e71147e9ec7234501c50f94860c58d/delorean.repo
        if repo.endswith('delorean.repo'):
            _data = repo.split('/')
            _hash = args.dlrn_hash_tag
            repo = "{}/{}/{}/{}/{}".format(_data[0],
                                           _hash[:2],
                                           _hash[2:4],
                                           _hash,
                                           _data[1])
    return repo


def _install_repos(args, base_path):
    def install_deps(args, base_path):
        if 'rhel' in args.distro:
            content = _get_rhel_trunk_candidate_repos(args, base_path)
            _write_repo(content, args.output_path, name="osp-trunk-candidate")
        else:
            content = _get_repo(base_path + "delorean-deps.repo", args)
            _write_repo(content, args.output_path)

    for repo in args.repos:
        if repo == "current":
            content = _get_repo(base_path + _get_dlrn_hash_tag(args, "current/delorean.repo"), args)
            _write_repo(content, args.output_path, name="delorean")
            install_deps(args, base_path)
        elif repo == "consistent":
            content = _get_repo(base_path + _get_dlrn_hash_tag(args, "consistent/delorean.repo"), args)
            _write_repo(content, args.output_path)
            install_deps(args, base_path)
        elif repo == "deps":
            install_deps(args, base_path)
        elif repo == "current-podified":
            content = _get_repo(base_path + _get_dlrn_hash_tag(args, "current-podified/delorean.repo"), args)
            _write_repo(content, args.output_path)
            install_deps(args, base_path)
        elif repo == "podified-ci-testing":
            content = _get_repo(base_path + _get_dlrn_hash_tag(args, "podified-ci-testing/delorean.repo"), args)
            _write_repo(content, args.output_path)
            install_deps(args, base_path)
        elif repo == "ceph":
            content = _create_ceph(args, "pacific")
            _write_repo(content, args.output_path)
        else:
            raise InvalidArguments('Invalid repo "%s" specified' % repo)

    distro = args.distro
    # CentOS-8 AppStream is required for UBI-8
    legacy_url = "centos/"
    if distro in ["ubi8", "ubi9"]:
        if not os.path.exists("/etc/distro.repos.d"):
            print(
                "WARNING: For UBI it is recommended to create "
                "/etc/distro.repos.d and rerun!"
            )
            dp_exists = False
        else:
            dp_exists = True
        if args.output_path == DEFAULT_OUTPUT_PATH and dp_exists:
            distro_path = "/etc/distro.repos.d"
        else:
            distro_path = args.output_path
        # TODO: Remove it once bugs are fixed
        # Add extra options to APPSTREAM_REPO_TEMPLATE because of
        # rhbz/1961558 and lpbz/1929634
        extra = ""
        distro_name = str(distro[-1]) + "-stream"
        content = APPSTREAM_REPO_TEMPLATE % {
            "mirror": args.mirror,
            "extra": extra,
            "legacy_url": legacy_url,
            "stream": distro_name,
        }
        _write_repo(content, distro_path)
        content = BASE_REPO_TEMPLATE % {
            "mirror": args.mirror,
            "legacy_url": legacy_url,
            "stream": distro_name,
        }
        _write_repo(content, distro_path)
        if distro in ["centos8", "centos9", "centos-10", "ubi8", "ubi9"]:
            distro = "centos" + str(distro[-1])

    if "centos" in distro:
        stream = str(distro.split('centos')[-1])
        # HA, Powertools are required for CentOS-8
        if int(stream) >= 8:
            if args.stream and not args.no_stream:
                stream = stream + "-stream"

            pt_name = "PowerTools"
            if "9" in stream or "10" in stream:
                legacy_url = ""
                pt_name = "CRB"

            content = HIGHAVAILABILITY_REPO_TEMPLATE % {
                "mirror": args.mirror,
                "stream": stream,
                "legacy_url": legacy_url,
            }
            _write_repo(content, args.output_path)

            content = POWERTOOLS_REPO_TEMPLATE % {
                "mirror": args.mirror,
                "stream": stream,
                "legacy_url": legacy_url,
                "pt_name": pt_name,
            }
            _write_repo(content, args.output_path)

            if "9" in stream or "10" in stream:
                content = APPSTREAM_REPO_TEMPLATE % {
                    "mirror": args.mirror,
                    "extra": "",
                    "legacy_url": legacy_url,
                    "stream": stream,
                }
                _write_repo(content, args.output_path)

                content = BASE_REPO_TEMPLATE % {
                    "mirror": args.mirror,
                    "legacy_url": legacy_url,
                    "stream": stream,
                }
                _write_repo(content, args.output_path)


def _run_pkg_clean(distro):
    pkg_mgr = "dnf"
    try:
        subprocess.check_call([pkg_mgr, "clean", "metadata"])
    except subprocess.CalledProcessError:
        print("ERROR: Failed to clean yum metadata.")
        raise


def main():
    distro_id, distro_major_version_id, distro_name = _get_distro()
    args = _parse_args(distro_id, distro_major_version_id)
    _validate_args(args, distro_name, distro_major_version_id)
    base_path = _get_base_path(args)
    _remove_existing(args)
    _install_repos(args, base_path)
    _run_pkg_clean(args.distro)


if __name__ == "__main__":
    main()
