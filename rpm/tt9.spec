# Copyright (c) 2026 Jolla Mobile Ltd.

Name:       tt9
Summary:    Keypad layouts and predictive dictionaries for Sailfish
Version:    1.0
Release:    1
# The builder is Apache-2.0. Each word list has its own terms; see %%license.
License:    Apache-2.0 and others
BuildArch:  noarch
URL:        https://github.com/sspanak/tt9
Source0:    %{name}-%{version}.tar.bz2
BuildRequires: python3-base

%description
Keypad layouts from Traditional T9, one <locale>.layout per language, plus
word lists for the locales named in dictionaries.list. The Sailfish keypad
reads both from %{_datadir}/keypad. A layout is enough for the letters.
Prediction needs the matching sqlite file, packaged per language as
%{name}-dictionary-<locale>.

The source archive unpacks to %{name}-%{version}/ and contains
build-dictionaries.py, languages.list, dictionaries.list and the tt9/
submodule checkout.

%package layouts
Summary:    Keypad layouts from Traditional T9
License:    Apache-2.0

%description layouts
Keypad layouts from Traditional T9, one <locale>.layout per language named in
languages.list.

# One package per word list: %1 package suffix, %2 locale.
# Keep in sync with dictionaries.list.
%define dictionary_package() \
%package dictionary-%1 \
Summary:    Keypad dictionary for %2 from Traditional T9 \
Requires:   %{name}-layouts \
%description dictionary-%1 \
Word list for %2 from Traditional T9, for keypad prediction. \
%files dictionary-%1 \
%%license tt9-notices/%2.txt tt9-notices/%2.license \
%{_datadir}/keypad/%2.sqlite

%dictionary_package ar-jo ar-JO
%dictionary_package de-de de-DE
%dictionary_package en en
%dictionary_package es-es es-ES
%dictionary_package fi-fi fi-FI
%dictionary_package fr-fr fr-FR
%dictionary_package hi-in hi-IN
%dictionary_package it-it it-IT
%dictionary_package pt-br pt-BR
%dictionary_package pt-pt pt-PT
%dictionary_package zh-cn zh-CN

%prep
%autosetup -n %{name}-%{version}

%build
# Relative output: mb2 skips %%prep and runs this in the repository, where
# the tt9 submodule is already checked out. A full rpmbuild does the same
# after %%autosetup, inside the unpacked archive.
python3 build-dictionaries.py --output tt9-data --notices tt9-notices \
    --from-list languages.list --dictionaries dictionaries.list

%install
mkdir -p %{buildroot}%{_datadir}/keypad
cp -a tt9-data/. %{buildroot}%{_datadir}/keypad/

%files layouts
%defattr(-,root,root,-)
%license tt9/LICENSE.txt
%dir %{_datadir}/keypad
%{_datadir}/keypad/*.layout
