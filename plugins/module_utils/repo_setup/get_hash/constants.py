#   Copyright 2021 Red Hat, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#
#
from __future__ import absolute_import, division, print_function


__metaclass__ = type


"""
These are the keys we expect to find in a well-formed config.yaml
If any keys are missing from the configuration hash resolution doesn't proceed.
"""
CONFIG_KEYS = [
    "dlrn_url",
    "repo_setup_releases",
    "repo_setup_ci_components",
    "rdo_named_tags",
    "os_versions",
]

"""
This is the path that we expect to find the system installed config.yaml.
The path is specified in [options.data_files] of the project setup.cfg.
"""
CONFIG_PATH = "/usr/local/etc/repo_setup_get_hash/config.yaml"

DEFAULT_CONFIG = {
    "repo_setup_releases": [
        "master",
        "antelope",
        "epoxy",
        "osp18",
    ],
    "dlrn_url": "https://trunk.rdoproject.org",
    "rdo_named_tags": [
        "current",
        "consistent",
        "component-ci-testing",
        "promoted-components",
        "podified-ci-testing",
        "current-podified",
        "current-podified-rdo",
    ],
    "repo_setup_ci_components": [
        "baremetal",
        "cinder",
        "clients",
        "cloudops",
        "common",
        "compute",
        "designate",
        "glance",
        "manila",
        "network",
        "octavia",
        "optimize",
        "security",
        "swift",
        "tempest",
        "podified",
        "ui",
        "validation",
    ],
    "os_versions": ["centos8", "centos9", "centos10", "rhel8", "rhel9"],
}
