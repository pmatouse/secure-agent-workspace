# RHDH container workspaces

An enrolled owner chooses **Container** in the existing RHDH create/update template, selects a site-approved BOM profile, and enters the provider credential. The existing owner picker handles deletion. The portal currently supports one registration per owner. VM is the default deployment.

The deployment selector filters the profile choices. Container choices are the
union of reviewed profiles configured for owners at this site, intersected with
the generated BOM catalog. The backend separately checks approval for the
authenticated owner before writing credentials. A profile available to another
owner is not automatically authorized for yours. With no reviewed container
profile, the form hides Container. Switching deployment may require selecting a
new profile; an existing container registration keeps its original profile.

If a request reports an unapproved profile, use one of the profiles named in the
error or have the administrator configure and qualify the required profile.
Foreground cleanup is a separate prerequisite (`portal.pruneOnRemove: true`).
Neither rejection changes the existing workspace or its stored credentials.

