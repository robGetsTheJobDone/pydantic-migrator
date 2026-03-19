"""Example versioned models used in the README and local experiments."""

from pydantic import Field

from pydantic_migrator import VersionedModel, versioned_model


@versioned_model("customer", 1)
class CustomerV1(VersionedModel):
    full_name: str
    email: str


@versioned_model("customer", 2)
class CustomerV2(VersionedModel):
    given_name: str
    family_name: str
    email: str


@versioned_model("customer", 3)
class CustomerV3(VersionedModel):
    given_name: str
    family_name: str
    primary_email: str = Field(alias="email")
