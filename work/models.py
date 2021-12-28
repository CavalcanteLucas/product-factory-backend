from django.conf import settings
from django.core.exceptions import ValidationError
from entitlements.exceptions import ValidationError as ValidError
from django.db import models, transaction
from django.contrib.postgres.fields import ArrayField
from django.db.models.signals import post_save
from django.dispatch import receiver
from model_utils import FieldTracker
from treebeard.mp_tree import MP_Node
from backend.mixins import TimeStampMixin, UUIDMixin
from backend.utils import send_email
from talent.models import Person, ProductPerson
from work.mixins import ProductMixin
from work.utils import get_person_data, to_dict


class Tag(TimeStampMixin):
    name = models.CharField(max_length=128)

    def __str__(self):
        return self.name


class Capability(MP_Node):
    name = models.CharField(max_length=255)
    description = models.TextField(max_length=1000, default='')
    video_link = models.CharField(max_length=255, blank=True, null=True)
    comments_start = models.ForeignKey(to='comments.capabilitycomment',
                                       on_delete=models.SET_NULL,
                                       null=True, editable=False)

    class Meta:
        db_table = 'capability'
        verbose_name_plural = 'capabilities'

    def __str__(self):
        return self.name


@receiver(post_save, sender=Capability)
def save_capability(sender, instance, created, **kwargs):
    if not created:
        # update tasklisting when capability info is updated
        TaskListing.objects.filter(capability=instance).update(capability_data=to_dict(instance))


class Attachment(models.Model):
    name = models.CharField(max_length=512)
    path = models.URLField()
    file_type = models.CharField(max_length=5, null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CapabilityAttachment(models.Model):
    capability = models.ForeignKey(Capability, on_delete=models.CASCADE)
    attachment = models.ForeignKey(Attachment, on_delete=models.CASCADE)

    class Meta:
        db_table = 'capability_attachment'


class CreateProductRequest(ProductMixin):
    STATUS_ACCEPTED = 0
    STATUS_NEW = 1
    STATUS_DECLINED = 2
    CREATE_PRODUCT_STATUS = (
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_NEW, "New"),
        (STATUS_DECLINED, "Declined")
    )
    created_by = models.ForeignKey(Person, on_delete=models.CASCADE)
    status = models.IntegerField(choices=CREATE_PRODUCT_STATUS, default=STATUS_NEW)
    tracker = FieldTracker()


@receiver(post_save, sender=CreateProductRequest)
def create_new_product(sender, instance, created, **kwargs):
    if not created:

        if instance.tracker.previous('status') == CreateProductRequest.STATUS_NEW and instance.status == \
                CreateProductRequest.STATUS_ACCEPTED:

            products = Product.objects.filter(name=instance.name).exists()

            try:
                if not products:
                    from commercial.models import ProductOwner

                    product_creator = instance.created_by
                    product_owner = ProductOwner.get_or_create(product_creator)

                    new_product = Product.objects.create(
                        photo=instance.photo,
                        name=instance.name,
                        short_description=instance.short_description,
                        full_description=instance.full_description,
                        website=instance.website,
                        video_url=instance.video_url,
                        is_private=instance.is_private,
                        owner=product_owner
                    )

                    current_headline = product_creator.headline
                    product_creator.headline = f'{current_headline}, Admin - {instance.name}' \
                        if len(current_headline) > 0 else f'Admin - {instance.name}'
                    product_creator.save()

                    new_product_person = ProductPerson(
                        person=product_creator,
                        product=new_product,
                        right=ProductPerson.PERSON_TYPE_PRODUCT_ADMIN
                    )
                    new_product_person.save()

            except BaseException as e:
                print("Exception:", e, flush=True)


class Product(ProductMixin):
    attachment = models.ManyToManyField(Attachment, related_name="product_attachements", blank=True)
    capability_start = models.ForeignKey(Capability, on_delete=models.CASCADE, null=True, editable=False)
    owner = models.ForeignKey('commercial.ProductOwner', on_delete=models.CASCADE, null=True)

    def get_members_emails(self):
        return self.productperson_set.all().values_list("person__email_address", flat=True)

    def is_product_member(self, person):
        return self.productperson_set.filter(person=person).exists()

    def get_product_owner(self):
        product_owner = self.owner
        return product_owner.organisation if product_owner.organisation else product_owner.person.user

    def __str__(self):
        return self.name


@receiver(post_save, sender=Product)
def save_product(sender, instance, created, **kwargs):
    if not created:
        # update tasklisting when product info is updated
        TaskListing.objects.filter(product=instance).update(
            product_data=dict(
                name=instance.name,
                slug=instance.slug,
                owner=instance.get_product_owner().username
            )
        )


class Initiative(TimeStampMixin, UUIDMixin):
    INITIATIVE_STATUS = (
        (1, "Active"),
        (2, "Completed")
    )
    name = models.TextField()
    product = models.ForeignKey(Product, on_delete=models.CASCADE, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    status = models.IntegerField(choices=INITIATIVE_STATUS, default=1)
    video_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name

    def get_available_tasks_count(self):
        return self.task_set.filter(status=Task.TASK_STATUS_AVAILABLE).count()

    def get_completed_task_count(self):
        return self.task_set.filter(status=Task.TASK_STATUS_DONE).count()

    def get_task_tags(self):
        return Tag.objects.filter(task_tags__initiative=self).distinct("id").all()

    @staticmethod
    def get_filtered_data(input_data, filter_data=None, exclude_data=None):
        if filter_data is None:
            filter_data = {}
        if not filter_data:
            filter_data = dict()

        if not input_data:
            input_data = dict()

        statuses = input_data.get("statuses", [])
        tags = input_data.get("tags", [])
        categories = input_data.get("categories", None)

        if statuses:
            filter_data["status__in"] = statuses

        if tags:
            filter_data["task__tag__in"] = tags

        if categories:
            filter_data["task__category__parent__in"] = categories

        queryset = Initiative.objects.filter(**filter_data)
        if exclude_data:
            queryset = queryset.exclude(**exclude_data)

        return queryset.distinct("id").all()


@receiver(post_save, sender=Initiative)
def save_initiative(sender, instance, created, **kwargs):
    if not created:
        # update tasklisting when initiative info is updated
        TaskListing.objects.filter(initiative=instance).update(initiative_data=to_dict(instance))


class TaskCategory(models.Model):
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, default=None,
                               related_name="children")
    active = models.BooleanField(default=False, db_index=True)
    selectable = models.BooleanField(default=False)
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    @staticmethod
    def get_active_categories(active=True, parent=None):
        return TaskCategory.objects.filter(active=active, parent=parent).all()

    @staticmethod
    def get_active_category_list(active=True):
        return TaskCategory.objects.filter(active=active, parent=None).values('id', 'name')


class Expertise(models.Model):
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, default=None,
                                related_name="expertise_children")
    category = models.ForeignKey(TaskCategory, on_delete=models.SET_NULL, null=True, blank=True, default=None,
                                related_name="category_expertise")
    selectable = models.BooleanField(default=False)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

    @staticmethod
    def get_category_expertise(category):
        return Expertise.objects.filter(category=category).values('id', 'name')

    @staticmethod
    def get_all_expertise(parent=None):
        return Expertise.objects.filter(parent=parent).all()

    @staticmethod
    def get_all_expertise_list():
        return Expertise.objects.filter(parent=None).values('id', 'name')


class Task(TimeStampMixin, UUIDMixin):
    TASK_STATUS_DRAFT = 0
    TASK_STATUS_BLOCKED = 1
    TASK_STATUS_AVAILABLE = 2
    TASK_STATUS_CLAIMED = 3
    TASK_STATUS_DONE = 4
    TASK_STATUS_IN_REVIEW = 5

    TASK_STATUS = (
        (TASK_STATUS_DRAFT, "Draft"),
        (TASK_STATUS_BLOCKED, "Blocked"),
        (TASK_STATUS_AVAILABLE, "Available"),
        (TASK_STATUS_CLAIMED, "Claimed"),
        (TASK_STATUS_DONE, "Done"),
        (TASK_STATUS_IN_REVIEW, "In review")
    )
    TASK_PRIORITY = (
        (0, 'High'),
        (1, 'Medium'),
        (2, 'Low')
    )
    initiative = models.ForeignKey(Initiative, on_delete=models.SET_NULL, blank=True, null=True)
    capability = models.ForeignKey(Capability, on_delete=models.SET_NULL, blank=True, null=True)
    title = models.TextField()
    description = models.TextField()
    short_description = models.TextField(max_length=256)
    status = models.IntegerField(choices=TASK_STATUS, default=0)
    attachment = models.ManyToManyField(Attachment, related_name="task_attachements", blank=True)
    tag = models.ManyToManyField(Tag, related_name="task_tags", blank=True)
    category = models.ForeignKey(TaskCategory, on_delete=models.CASCADE, related_name="task", 
                                    blank=True, null=True, default=None)
    expertise = models.ManyToManyField(Expertise, related_name="task_expertise")
    blocked = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    priority = models.IntegerField(choices=TASK_PRIORITY, default=1)
    published_id = models.IntegerField(default=0, blank=True, editable=False)
    auto_approve_task_claims = models.BooleanField(default=True)
    created_by = models.ForeignKey("talent.Person", on_delete=models.CASCADE, blank=True, null=True,
                                   related_name="created_by")
    updated_by = models.ForeignKey("talent.Person", on_delete=models.CASCADE, blank=True, null=True,
                                   related_name="updated_by")
    tracker = FieldTracker()
    comments_start = models.ForeignKey(to="comments.taskcomment", on_delete=models.SET_NULL, null=True, editable=False)
    reviewer = models.ForeignKey("talent.Person", on_delete=models.SET_NULL, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True)
    video_url = models.URLField(blank=True, null=True)
    contribution_guide = models.ForeignKey("contribution_management.ContributorGuide",
                                           null=True,
                                           default=None,
                                           blank=True,
                                           on_delete=models.SET_NULL)

    class Meta:
        verbose_name_plural = "Tasks"

    def __str__(self):
        return self.title

    @staticmethod
    def get_filtered_data(input_data, filter_data=None, exclude_data=None):
        if not filter_data:
            filter_data = {}

        if not input_data:
            input_data = {}

        sorted_by = input_data.get("sorted_by", "title")
        statuses = input_data.get("statuses", [])
        tags = input_data.get("tags", [])
        priority = input_data.get("priority", [])
        assignee = input_data.get("assignee", [])
        task_creator = input_data.get("task_creator", [])
        categories = input_data.get("categories", [])

        if statuses:
            filter_data["status__in"] = statuses

        if tags:
            filter_data["tag__in"] = tags

        if priority:
            filter_data["priority__in"] = priority

        if task_creator:
            filter_data["created_by__in"] = task_creator

        if assignee:
            filter_data["taskclaim__kind__in"] = [0, 1]
            filter_data["taskclaim__person_id__in"] = assignee

        if categories:
            filter_data["category__parent__in"] = categories

        queryset = Task.objects.filter(**filter_data)
        if exclude_data:
            queryset = queryset.exclude(**exclude_data)

        return queryset.order_by(sorted_by).all()

    def get_task_link(self, show_domain_name=True):
        try:
            product = self.producttask_set.first().product
            product_owner = product.get_product_owner()
            domain_name = settings.FRONT_END_SERVER if show_domain_name else ""
            return f"{domain_name}/{product_owner.username}/{product.slug}/tasks/{self.published_id}"
        except ProductTask.DoesNotExist:
            return None


@receiver(post_save, sender=Task)
def save_task(sender, instance, created, **kwargs):
    # If task changed status to available/claimed/done
    try:
        reviewer = instance.reviewer

        # set contributor role for user if task is done
        if instance.status == Task.TASK_STATUS_DONE and instance.tracker.previous('status') != Task.TASK_STATUS_DONE:
            try:
                task_claim = instance.taskclaim_set.filter(kind=0).first()
                if task_claim:
                    product_person_data = dict(
                        product_id=instance.product.id,
                        person_id=task_claim.person.id
                    )
                    if not ProductPerson.objects.filter(**product_person_data,
                                                        right__in=[ProductPerson.PERSON_TYPE_CONTRIBUTOR,
                                                                   ProductPerson.PERSON_TYPE_PRODUCT_ADMIN,
                                                                   ProductPerson.PERSON_TYPE_PRODUCT_MANAGER]).exists():
                        with transaction.atomic():
                            ProductPerson.objects.create(**product_person_data,
                                                         right=ProductPerson.PERSON_TYPE_CONTRIBUTOR)
            except Exception as e:
                print("Failed to change a user role", e, flush=True)

        if instance.tracker.previous('status') != instance.status \
                and instance.status == Task.TASK_STATUS_CLAIMED \
                and reviewer:
            send_email(
                to_emails=reviewer.email_address,
                subject='Task status changed',
                content=f"""
                    The task {instance.title} is claimed now.
                    You can see the task here: {instance.get_task_link()}
                """
            )
    except Person.DoesNotExist:
        pass

    task_listing_data = dict(
        title=instance.title,
        description=instance.description,
        short_description=instance.short_description,
        status=instance.status,
        tags=list(instance.tag.all().values_list('name', flat=True)),
        blocked=instance.blocked,
        featured=instance.featured,
        priority=instance.priority,
        published_id=instance.published_id,
        auto_approve_task_claims=instance.auto_approve_task_claims,
        task_creator_id=str(instance.created_by.id) if instance.created_by.id else None,
        created_by=get_person_data(instance.created_by),
        updated_by=get_person_data(instance.updated_by),
        reviewer=get_person_data(instance.reviewer) if instance.reviewer else None,
        product_data={
            "name": instance.product.name,
            "slug": instance.product.slug,
            "owner": instance.product.get_product_owner().username,
            "website": instance.product.website,
            "detail_url": instance.product.detail_url,
            "video_url": instance.product.video_url
        } if instance.product else None,
        product=instance.product,
        has_active_depends=Task.objects.filter(taskdepend__task=instance.id).exclude(
            status=Task.TASK_STATUS_DONE).exists(),
        initiative_id=instance.initiative.id if instance.initiative else None,
        initiative_data=to_dict(instance.initiative) if instance.initiative else None,
        capability_id=instance.capability.id if instance.capability is not None else None,
        capability_data=to_dict(instance.capability) if instance.capability else None,
        in_review=instance.taskclaim_set.filter(kind=0).count() > 0,
        video_url=instance.video_url,
    )

    task_claim = instance.taskclaim_set.filter(kind__in=[0, 1]).first()

    if task_claim:
        task_listing_data["task_claim"] = to_dict(task_claim)
        task_listing_data["assigned_to_data"] = get_person_data(task_claim.person)
        task_listing_data["assigned_to_person_id"] = task_claim.person.id if task_claim.person else None
    else:
        task_listing_data["task_claim"] = None
        task_listing_data["assigned_to_data"] = None
        task_listing_data["assigned_to_person_id"] = None

    if created:
        product = instance.product
        last_product_task = None
        if product:
            last_product_task = Task.objects \
                .filter(producttask__product=product) \
                .order_by('-published_id').last()
        published_id = last_product_task.published_id + 1 if last_product_task else 1
        instance.published_id = published_id
        instance.save()

        task_listing_data["published_id"] = published_id

    # create TaskListing object
    tasklisting_exist = TaskListing.objects.filter(task=instance).exists()

    if tasklisting_exist:
        TaskListing.objects.filter(task=instance).update(**task_listing_data)
    else:
        TaskListing.objects.create(
            task=instance,
            **task_listing_data
        )


class TaskListing(models.Model):
    task = models.OneToOneField(Task, on_delete=models.CASCADE, unique=True)
    title = models.TextField()
    description = models.TextField()
    short_description = models.TextField(max_length=256)
    status = models.IntegerField(choices=Task.TASK_STATUS, default=0)
    tags = ArrayField(ArrayField(models.CharField(max_length=254)))
    blocked = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    priority = models.IntegerField(choices=Task.TASK_PRIORITY, default=1)
    published_id = models.IntegerField(default=0, blank=True, editable=False)
    auto_approve_task_claims = models.BooleanField(default=True)
    task_creator = models.ForeignKey(Person, on_delete=models.SET_NULL, related_name="creator", null=True)
    created_by = models.JSONField()
    updated_by = models.JSONField()
    reviewer = models.JSONField(null=True)
    product_data = models.JSONField(null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True)
    video_url = models.URLField(blank=True, null=True)

    task_claim = models.JSONField(null=True)
    assigned_to_data = models.JSONField(null=True)
    assigned_to_person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, related_name="task_listing")
    has_active_depends = models.BooleanField(default=False)
    initiative = models.ForeignKey(Initiative, on_delete=models.SET_NULL, null=True)
    initiative_data = models.JSONField(null=True)
    capability = models.ForeignKey(Capability, on_delete=models.SET_NULL, null=True)
    capability_data = models.JSONField(null=True)

    in_review = models.BooleanField(default=False)

    @staticmethod
    def get_filtered_data(input_data, filter_data=None, exclude_data=None):
        if not filter_data:
            filter_data = {}

        if not input_data:
            input_data = {}

        sorted_by = input_data.get("sorted_by", "title")

        statuses = input_data.get("statuses", [])
        tags = input_data.get("tags", [])
        priority = input_data.get("priority", [])
        assignee = input_data.get("assignee", [])
        categories = input_data.get("categories", [])
        task_creator = input_data.get("task_creator", [])

        if statuses:
            filter_data["status__in"] = statuses

        if Task.TASK_STATUS_AVAILABLE in statuses:
            filter_data["has_active_depends"] = False

        if tags:
            filter_data["tags__contains"] = tags

        if categories:
            filter_data["task__category__parent__in"] = categories

        if priority:
            filter_data["priority__in"] = priority

        if task_creator:
            filter_data["task_creator_id__in"] = task_creator

        if assignee:
            filter_data["assigned_to_person_id__in"] = assignee

        queryset = TaskListing.objects.filter(**filter_data)
        if exclude_data:
            queryset = queryset.exclude(**exclude_data)

        return queryset.distinct().order_by(sorted_by).all()


class TaskDepend(models.Model):
    task = models.ForeignKey(to=Task, on_delete=models.CASCADE, related_name='Task')
    depends_by = models.ForeignKey(to=Task, on_delete=models.CASCADE)

    class Meta:
        db_table = 'work_task_depend'


class ProductTask(TimeStampMixin, UUIDMixin):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.CASCADE)


@receiver(post_save, sender=ProductTask)
def save_product_task(sender, instance, created, **kwargs):
    if created:
        task = instance.task
        last_product_task = Task.objects \
            .filter(producttask__product=instance.product) \
            .order_by('-published_id').first()
        task.published_id = last_product_task.published_id + 1 if last_product_task else 1
        task.save()


class CodeRepository(TimeStampMixin, UUIDMixin):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, blank=True, null=True)
    repository = models.URLField(blank=True, null=True)
    git_owner = models.CharField(max_length=255)
    git_access_token = models.CharField(max_length=65)

    class Meta:
        verbose_name_plural = "CodeRepositories"

    def __str__(self):
        return f"{self.product.name} - {self.repository}"
