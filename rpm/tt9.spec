# Copyright (c) 2026 Jolla Mobile Ltd.

Name:       tt9
Summary:    Predictive dictionaries for the Sailfish keypad
Version:    1.0
Release:    1
# The builder is Apache-2.0. Each word list has its own terms; see %%license.
License:    Apache-2.0 and others
BuildArch:  noarch
URL:        https://github.com/sspanak/tt9
Source0:    %{name}-%{version}.tar.bz2
BuildRequires: python3-base

%description
Word lists and keypad layouts from Traditional T9, built into the layout
and sqlite pairs the Sailfish keypad reads from %{_datadir}/tt9.
languages.list currently names English and Finnish. A language is offered
only when both of its files are installed.

The source archive unpacks to %{name}-%{version}/ and contains
build-dictionaries.py, languages.list and the tt9/ submodule checkout.

%prep
%autosetup -n %{name}-%{version}

%build
# Relative output: mb2 skips %%prep and runs this in the repository, where
# the tt9 submodule is already checked out. A full rpmbuild does the same
# after %%autosetup, inside the unpacked archive.
python3 build-dictionaries.py --output tt9-data --notices tt9-notices --from-list languages.list

%install
mkdir -p %{buildroot}%{_datadir}/tt9
cp -a tt9-data/. %{buildroot}%{_datadir}/tt9/

# Create filelist
{
    FILESLIST=${PWD}/files.list
    pushd %{buildroot}
    find .%{_datadir}/tt9 -type d | sed -e "s/^\./%%dir /g" > $FILESLIST
    find .%{_datadir}/tt9 -type f | sed -e "s/^\.//g" >> $FILESLIST
    popd
}

%files -f files.list -f tt9-notices/files.list
%defattr(-,root,root,-)
%license tt9/LICENSE.txt
