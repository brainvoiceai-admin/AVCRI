# Therapy Scheduling Module Setup Guide

## Overview
This guide explains how to set up the therapy scheduling module with proper permissions and role-based access control in the AVCRI system.

## Module Features

### 🎯 **Core Functionality**
- **Therapy Scheduling Dashboard**: Manage draft, failed, and scheduled therapies
- **Algorithm Integration**: Uses `final_allocation.py` for intelligent scheduling
- **Role-Based Access**: Different permission levels for different user types
- **Admin Interface**: Comprehensive Django admin for data management
- **API Endpoints**: RESTful APIs for frontend integration

### 🔐 **Permission Levels**

#### 1. **Super Admin**
- Full access to all modules including therapy scheduling
- Can manage all therapy allocations and bookings
- Access to all admin functions

#### 2. **Admin**
- Full access to therapy scheduling module
- Can view and modify all therapy allocations
- Access to scheduling dashboard and admin interface
- Can manage user permissions

#### 3. **Scheduling Staff**
- Dedicated access to therapy scheduling module
- Can create, modify, and schedule therapy allocations
- Access to scheduling dashboard and API endpoints
- Can manage therapist assignments

#### 4. **Doctor**
- Access to therapy scheduling for patient care
- Can view and create therapy allocations for their patients
- Limited access to scheduling dashboard
- Can view therapist assignments

#### 5. **Therapist**
- View-only access to therapy schedules
- Can see their assigned therapies
- Cannot modify scheduling or allocations
- Access to their therapy schedule

## Setup Instructions

### 1. **Run the Setup Command**
```bash
python manage.py setup_scheduling_module
```

This command will:
- Create the therapy scheduling module
- Set up role-based permissions
- Update existing users with appropriate access
- Configure module access for different user roles

### 2. **Force Update (if needed)**
```bash
python manage.py setup_scheduling_module --force
```

Use this if you need to update existing module configurations.

### 3. **Verify Setup**
After running the setup command, verify that:
- The therapy scheduling module appears in the admin interface
- Users have appropriate permissions based on their roles
- The scheduling dashboard is accessible at `/sheduling/scheduling/`

## Module Configuration

### **Module Details**
- **Name**: `therapy_scheduling`
- **Display Name**: Therapy Scheduling
- **URL**: `/sheduling/scheduling/`
- **Icon**: 📅
- **Order**: 10

### **Role Permissions**

#### **Super Admin Role**
- Access to all modules including therapy scheduling
- Full administrative privileges

#### **Scheduling Staff Role**
- Therapy scheduling module
- Patient lookup
- Therapy schedule
- Treatment schedule
- Reports

#### **Doctor Role**
- Therapy scheduling module
- Patient lookup
- Add therapy
- Add prescription
- Treatment schedule
- Reports

#### **Therapist Role**
- Therapy scheduling module (view-only)
- Therapy schedule
- Treatment schedule

#### **Admin Role**
- Therapy scheduling module
- User management
- Demand prediction
- Audit log
- Master tables
- Reports

## API Endpoints

### **Main Dashboard**
- `GET /sheduling/scheduling/` - Main scheduling dashboard

### **API Endpoints**
- `POST /sheduling/scheduling/api/schedule-therapies/` - Trigger scheduling algorithm
- `GET /sheduling/scheduling/api/therapy-data/` - Fetch therapy data
- `POST /sheduling/scheduling/api/reschedule-therapy/` - Reschedule single therapy
- `POST /sheduling/scheduling/api/reschedule-all-failed/` - Reschedule all failed therapies

### **Access Control**
All API endpoints are protected with role-based access control:
- Authentication required
- Module access verification
- Role-based permission checks

## Admin Interface

### **Models Available in Admin**
1. **PatientSnapshot** - Patient information
2. **TherapyAllocation** - Main therapy allocations
3. **Booking** - Individual therapy bookings
4. **BookingItem** - Therapy items and requirements
5. **BookingAssignment** - Therapist assignments
6. **PrescriptionAllocation** - Prescription allocations
7. **CancellationRequest** - Therapy cancellation requests
8. **NotificationQueue** - System notifications
9. **TherapyNotification** - Therapy-specific notifications
10. **AuditLog** - System audit logs
11. **AllocationChange** - Therapy allocation changes
12. **PrescriptionNotification** - Prescription notifications
13. **PrescriptionChange** - Prescription changes

### **Admin Features**
- **Advanced Filtering**: Filter by status, date, user, etc.
- **Search Functionality**: Search by patient name, therapy name, etc.
- **Bulk Operations**: Mass update operations
- **Detailed Views**: Comprehensive form layouts
- **Audit Trail**: Track all changes and modifications

## User Management

### **Assigning Roles**
1. **Via Admin Interface**:
   - Go to Django Admin → Users
   - Select a user
   - Assign appropriate role
   - Save changes

2. **Via Management Command**:
   ```bash
   python manage.py setup_scheduling_module
   ```

3. **Programmatically**:
   ```python
   from authentication.models import Role
   from django.contrib.auth import get_user_model
   
   User = get_user_model()
   user = User.objects.get(username='username')
   role = Role.objects.get(name='scheduling_staff_role')
   user.custom_role = role
   user.save()
   ```

### **Permission Verification**
Check if a user has access to therapy scheduling:
```python
user.has_module_access('therapy_scheduling')
```

## Security Features

### **Access Control**
- **Authentication Required**: All endpoints require user authentication
- **Module Access**: Users must have access to therapy scheduling module
- **Role-Based Permissions**: Different access levels based on user roles
- **API Protection**: All API endpoints are protected with decorators

### **Audit Logging**
- **User Actions**: Track all user actions in the system
- **Therapy Changes**: Log all therapy allocation modifications
- **Scheduling Events**: Record scheduling algorithm executions
- **Permission Changes**: Track role and permission modifications

### **Data Protection**
- **Input Validation**: All inputs are validated and sanitized
- **SQL Injection Prevention**: Django ORM provides protection
- **XSS Prevention**: Proper HTML escaping in templates
- **CSRF Protection**: CSRF tokens for all forms and API calls

## Troubleshooting

### **Common Issues**

#### **1. Module Not Appearing**
- Run the setup command: `python manage.py setup_scheduling_module`
- Check if the module is active in the admin interface
- Verify user has appropriate role assigned

#### **2. Permission Denied**
- Check user's role and custom role assignment
- Verify module access permissions
- Ensure user is authenticated

#### **3. API Access Issues**
- Check authentication status
- Verify module access permissions
- Check role-based access control

#### **4. Admin Interface Issues**
- Ensure all models are properly registered
- Check for any import errors
- Verify database migrations are applied

### **Debug Commands**
```bash
# Check module status
python manage.py shell
>>> from authentication.models import Module
>>> Module.objects.filter(name='therapy_scheduling')

# Check user permissions
>>> user = User.objects.get(username='username')
>>> user.has_module_access('therapy_scheduling')

# Check role assignments
>>> user.custom_role
>>> user.role
```

## Maintenance

### **Regular Tasks**
1. **Monitor Audit Logs**: Review system audit logs regularly
2. **User Permission Reviews**: Periodically review user permissions
3. **Module Updates**: Keep module configurations up to date
4. **Security Audits**: Regular security and permission audits

### **Backup Considerations**
- **User Roles**: Backup role and permission configurations
- **Module Settings**: Backup module configurations
- **Audit Logs**: Archive old audit logs
- **Therapy Data**: Regular backup of therapy allocations and bookings

## Support

### **Documentation**
- **API Documentation**: Available in the codebase
- **Admin Guide**: Django admin interface documentation
- **User Manual**: End-user documentation for the scheduling dashboard

### **Technical Support**
- **Code Issues**: Check the implementation in `Sheduling/` app
- **Permission Issues**: Review `authentication/` app configuration
- **Database Issues**: Check Django migrations and database integrity

## Conclusion

The therapy scheduling module provides a comprehensive solution for managing therapy allocations with proper role-based access control. The setup process ensures that users have appropriate permissions based on their roles, and the system maintains security and audit trails throughout the scheduling process.

For additional support or questions, refer to the main system documentation or contact the development team.
