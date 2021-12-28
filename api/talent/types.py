import datetime

import graphene
from graphene import InputObjectType
from graphene_django.types import DjangoObjectType, ObjectType

from matching.models import CLAIM_TYPE_ACTIVE
from talent.models import Person, ProductPerson, PersonProfile, Review, PersonSocial, PersonSkill, PersonWebsite
from work.models import Task, Product, Initiative
from matching.models import TaskDeliveryAttempt, TaskDeliveryAttachment

class PersonSocialType(DjangoObjectType):
    class Meta:
        model = PersonSocial


class PersonType(DjangoObjectType):
    photo = graphene.String(required=False)
    slug = graphene.String()
    claimed_task = graphene.Field("api.work.types.TaskType")
    username = graphene.String()

    class Meta:
        model = Person

    def resolve_photo(self, info):
        """Resolve product image absolute path"""
        if self.photo:
            return info.context.build_absolute_uri(self.photo.url)
        return None

    def resolve_slug(self, info):
        return self.slug

    def resolve_username(self, info):
        return self.user.username

    def resolve_claimed_task(self, info):
        claimed_task = self.taskclaim_set.filter(kind=CLAIM_TYPE_ACTIVE).last()
        return claimed_task.task if claimed_task else None


class SkillInput(graphene.InputObjectType):
    category = graphene.List(graphene.String, required=True)
    expertise = graphene.List(graphene.String, required=False)


class WebsiteInput(graphene.InputObjectType):
    website = graphene.String(required=True)
    type = graphene.String(required=True)


class PersonInput(graphene.InputObjectType):
    first_name = graphene.String(required=True)
    last_name = graphene.String(required=True)
    bio = graphene.String(required=True)
    skills = graphene.List(SkillInput, required=False)
    avatar = graphene.Int(required=False)
    websites = graphene.List(WebsiteInput, required=False)


class ProductPersonType(DjangoObjectType):
    class Meta:
        model = ProductPerson
        convert_choices_to_enum = False


class ProductPersonsType(graphene.ObjectType):
    product_team = graphene.List(PersonType)
    contributors = graphene.List(PersonType)


class PersonProfileType(DjangoObjectType):
    class Meta:
        model = PersonProfile


class ReviewType(DjangoObjectType):
    class Meta:
        model = Review


class ReviewInput(graphene.InputObjectType):
    person_id = graphene.Int(
        description="User Id",
        required=True
    )


class ProductReviewType(ObjectType):
    product_reviews = graphene.List(ReviewType)
    review = graphene.Field(ReviewType)


class SkillType(DjangoObjectType):
    class Meta:
        model = PersonSkill


class Attachment(DjangoObjectType):
    class Meta:
        model = TaskDeliveryAttachment


class DeliveryAttemptType(DjangoObjectType):
    message = graphene.String()
    attachments = graphene.List(Attachment)

    class Meta:
        model = TaskDeliveryAttempt

    def resolve_message(self, info):
        return self.delivery_message

    def resolve_attachments(self, info):
        return self.attachments.all()


class WebsiteType(DjangoObjectType):
    class Meta:
        model = PersonWebsite
        convert_choices_to_enum = False


class PersonPortfolioType(DjangoObjectType):
    class Meta:
        model = Person

    bio = graphene.String()
    avatar = graphene.String()
    skills = graphene.List(SkillType)
    websites = graphene.List(WebsiteType)
    website_types = graphene.List(graphene.String)

    def resolve_bio(self, info):
        profile = self.profile.last()
        return profile.overview

    def resolve_avatar(self, info):
        profile = self.profile.last()
        if profile:
            avatar = profile.avatar if profile.avatar else None
            return avatar.avatar if avatar else None

    def resolve_skills(self, info):
        profile = self.profile.last()
        if profile:
            return profile.skills.all()
        return []

    def resolve_websites(self, info):
        profile = self.profile.last()
        if profile:
            return profile.websites.all()
        return []

    def resolve_website_types(self, info):
        return [website_type[1] for website_type in PersonWebsite.WebsiteType]


class ReviewerType(DjangoObjectType):
    class Meta:
        model = Person
    username = graphene.String()
    avatar = graphene.String()
    link = graphene.String()

    def resolve_avatar(self, info):
        profile = self.profile.last()
        return profile.avatar.avatar if profile and profile.avatar else None

    def resolve_username(self, info):
        return self.user.username

    def resolve_link(self, info):
        return self.slug


class ProductCustomType(DjangoObjectType):
    class Meta:
        model = Product

    avatar = graphene.String()
    name = graphene.String()
    link = graphene.String()

    def resolve_avatar(self, info):
        return self.photo

    def resolve_name(self, info):
        return self.name

    def resolve_link(self, info):
        return f"{self.get_product_owner().username}/{self.slug}"


class InitiativePersonType(DjangoObjectType):
    class Meta:
        model = Initiative

    link = graphene.String()

    def resolve_link(self, info):
        product_name = self.product.slug
        product_owner = self.product.get_product_owner().username
        return f"{product_owner}/{product_name}/initiatives/{self.id}"


class PersonTask(DjangoObjectType):
    class Meta:
        model = Task

    category = graphene.Field("api.work.types.TaskCategoryType")
    expertise = graphene.List("api.work.types.ExpertiseType")
    reviewer_person = graphene.Field(ReviewerType)
    product = graphene.Field(ProductCustomType)
    initiative = graphene.Field(InitiativePersonType)
    date = graphene.Int()
    link = graphene.String()

    def resolve_date(self, info):
        days = (datetime.datetime.now() - self.updated_at.replace(tzinfo=None)).days
        return days if days > 0 else 0

    def resolve_category(self, info):
        return self.category

    def resolve_expertise(self, info):
        return self.expertise.all()

    def resolve_product(self, info):
        return self.product

    def resolve_reviewer_person(self, info):
        return self.reviewer

    def resolve_initiative(self, info):
        return self.initiative

    def resolve_link(self, info):
        owner = self.product.get_product_owner().username
        product = self.product.slug
        task_id = self.published_id
        return f"{owner}/{product}/tasks/{task_id}"


class FilterType(InputObjectType):
    sorted_by = graphene.String(required=False)
    categories = graphene.List(graphene.String, required=False)
    tags = graphene.List(graphene.String, required=False)
    priority = graphene.List(graphene.String, required=False)
    task_creator = graphene.List(graphene.String, required=False)


class PersonPaginatedTasks(ObjectType):
    page = graphene.Int()
    pages = graphene.Int()
    has_next = graphene.Boolean()
    has_prev = graphene.Boolean()
    tasks = graphene.List(PersonTask)
